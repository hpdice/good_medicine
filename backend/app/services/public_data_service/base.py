"""동기화 서비스 공통 기반 — HTTP 페이지 조회·재시도, Drug 레코드 확보,
행 upsert처럼 여러 소스가 공유하는 인프라만 담는다. 특정 DUR 판정 규칙
(병용금기·효능군중복·연령대금기) upsert는 dur_sync.py로 분리."""
import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient

from . import raw_store
from .helpers import _clean, _make_drug_key, _make_simple_name


class _SyncBase:
    PAGE_SIZE = 100

    def __init__(self, db: AsyncSession, progress_cb=None) -> None:
        self.db = db
        self._api_key = settings.PUBLIC_DATA_API_KEY
        self._progress_cb = progress_cb
        # 성분 sweep에서 같은 키((drug_id, ingr_code), (code_a, code_b) 등)가 수천 번 다시
        # 나오므로, 이번 실행에서 이미 본 키는 DB 왕복 없이 건너뛴다.
        self._seen: set[tuple] = set()
        # 이번 실행에서 금기 사유 문장이 바뀌어 갱신된 성분쌍 규칙 수(로그·검증용)
        self._updated_ingr_contra = 0
        # item_seq -> Drug — 같은 품목이 병용금기 수십~수백 쌍에 반복 등장하므로
        # (예: 흔한 진통제 한 품목이 수백 개 다른 품목과 쌍을 이룸) 캐시 없이는
        # _find_or_create_drug_from_dur가 매번 DB 왕복한다(796,842행 sweep에서 가장 큰 시간 비중을
        # 차지한다).
        self._drug_by_seq: dict[str, Drug] = {}
        # 원본 응답 보관(bronze). replay_snapshot이 있으면 API 대신 저장된 파일에서 읽는다
        # ("latest" = 엔드포인트별 가장 최근 스냅샷). 재파싱 시엔 새로 저장하지 않는다.
        self.replay_snapshot: str | None = None
        # DUR 품목정보(`DURPrdlstInfoService03`)만: 이 날짜(YYYYMMDD) 이후 바뀐 행만 받는다(`start_change_date`).
        # 이미 적재한 행을 다시 받지 않아 병용금기 79만 행 sweep(7시간)이 변경분(수만 행, 수 분)으로 준다.
        self.change_since: str | None = None
        self._raw_snapshot = raw_store.today_snapshot()

    async def _emit(self, **kwargs) -> None:
        if self._progress_cb:
            await self._progress_cb(kwargs)

    async def _fetch_page(self, client: httpx.AsyncClient, url: str, params: dict, retries: int = 5) -> dict | None:
        """페이지 요청. 429는 60초 대기 후 재시도, 그 외 에러는 지수 백오프.
        성공한 응답은 원본 그대로 파일에 보관하고(`raw_store`), replay 모드면 파일에서 읽는다."""
        if self.replay_snapshot:
            return await asyncio.to_thread(self._load_raw_page, url, params)
        for attempt in range(retries):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                await self._save_raw_page(url, params, data)
                return data
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 60
                    logger.warning(f"Rate limit (attempt {attempt + 1}/{retries}, page {params.get('pageNo')}): retrying in {wait}s")
                else:
                    wait = 2 ** attempt
                    logger.warning(f"API error (attempt {attempt + 1}/{retries}, page {params.get('pageNo')}): {e}. retrying in {wait}s")
                await asyncio.sleep(wait)
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"API error (attempt {attempt + 1}/{retries}, page {params.get('pageNo')}): {e}. retrying in {wait}s")
                await asyncio.sleep(wait)
        logger.error(f"API failed after {retries} attempts, skipping page {params.get('pageNo')}")
        return None

    async def _save_raw_page(self, url: str, params: dict, data: dict) -> None:
        if not settings.RAW_RESPONSE_SAVE:
            return
        try:
            await asyncio.to_thread(
                raw_store.save_page, raw_store.endpoint_name(url), self._raw_snapshot, int(params["pageNo"]), data
            )
        except Exception as e:  # 보관 실패가 적재를 막으면 안 된다
            logger.warning(f"raw 응답 저장 실패(동기화는 계속): {e}")

    def _load_raw_page(self, url: str, params: dict) -> dict | None:
        endpoint = raw_store.endpoint_name(url)
        snapshot = self.replay_snapshot
        if snapshot is None:  # replay 모드에서만 불린다 — 방어적 처리
            return None
        if snapshot == "latest":
            snapshot = raw_store.latest_snapshot(endpoint)
            if snapshot is None:
                logger.error(f"replay할 raw 스냅샷이 없음: {endpoint}")
                return None
        return raw_store.load_page(endpoint, snapshot, int(params["pageNo"]))

    # ------------------------------------------------------------------ #
    # 페이지네이션 — 모든 동기화가 이 한 벌을 쓴다                             #
    # ------------------------------------------------------------------ #

    async def _pages(
        self, url: str, *, size: int, label: str, start: int = 1, delay: float = 0.5,
    ) -> AsyncIterator[tuple[int, list[dict], int]]:
        """`url`의 페이지를 (페이지 번호, 항목들, totalCount)로 하나씩 내준다.

        아래 두 경우는 건너뛰지 않고 중단한다 — 건너뛰면 그만큼 규칙이 빠진 채 "완료"로 끝난다.
        1. 재시도를 다 쓰고도 요청이 실패한 페이지.
        2. 비어 있는데 정상적인 끝이 아닌 응답. 할당량 초과·스로틀은 HTTP 200 + 빈 body로 와서
           정상 EOF처럼 보이므로, 오류 메시지가 있거나 totalCount상 아직 마지막 페이지가 아니면 중단으로 본다.
        적재는 멱등(upsert)이라 재실행하면 안전하게 다시 받는다."""
        page = start
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"serviceKey": self._api_key, "pageNo": page, "numOfRows": size, "type": "json"}
                if self.change_since and url.startswith(settings.DUR_PRODUCT_API_URL):
                    params["start_change_date"] = self.change_since
                data = await self._fetch_page(client, url, params)
                if data is None:
                    raise RuntimeError(f"{label} page {page} 요청 실패(재시도 소진) — 건너뛰지 않고 중단. 재실행 필요.")

                body = data.get("body", {})
                items: list[dict] = body.get("items", [])
                total: int = body.get("totalCount", 0)
                if not items:
                    err = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {}).get("errMsg")
                    last_page = -(-total // size) if total else 0
                    if err or (last_page and page < last_page):
                        raise RuntimeError(
                            f"{label} page {page}/{last_page} 빈 응답 (err={err}) — 할당량 초과일 수 있음. "
                            f"리셋 후 재실행하면 이어서 진행."
                        )
                    return

                yield page, items, total

                if len(items) < size:
                    return
                page += 1
                await asyncio.sleep(delay)

    async def _sync_endpoint(
        self, url: str, handler, *, source: str, label: str, size: int | None = None,
        start: int = 1, delay: float = 0.5, on_page_done=None,
    ) -> int:
        """한 엔드포인트를 끝까지 돌며 `await handler(item)`을 부르고 페이지마다 커밋한다.
        `on_page_done(다음에 받을 페이지)`는 체크포인트 같은 이어받기 지점 기록용."""
        count = 0
        async for page, items, total in self._pages(
            url, size=size or self.PAGE_SIZE, label=label, start=start, delay=delay,
        ):
            for item in items:
                await handler(item)
            count += len(items)
            await self.db.commit()
            logger.info(f"Synced {label} page {page} ({count}/{total})")
            await self._emit(source=source, page=page, count=count, total=total)
            if on_page_done:
                on_page_done(page + 1)
        return count

    async def _run_multi_endpoint_sync(
        self, ops: dict[str, tuple[str, Any]], handler, *, source: str, size: int | None = None,
        base_url: str | None = None,
    ) -> int:
        """`ops`: {label: (엔드포인트 op, handler에 넘길 부가값)}을 차례로 돈다.
        `handler(item, 부가값)`. `base_url` 기본값은 DUR 품목정보 서비스."""
        processed = 0
        for label, (op, extra) in ops.items():
            async def handle(item: dict, _extra=extra) -> None:
                await handler(item, _extra)

            processed += await self._sync_endpoint(
                f"{base_url or settings.DUR_PRODUCT_API_URL}/{op}", handle,
                source=f"{source}:{label}", label=f"{source} [{label}]", size=size,
            )
        return processed

    # ------------------------------------------------------------------ #
    # Drug 레코드 확보 — 여러 sync가 공유                                    #
    # ------------------------------------------------------------------ #

    async def _find_drug_by_name(self, name: str) -> Drug | None:
        drug_key = _make_drug_key(name)
        return await self.db.scalar(select(Drug).where(Drug.drug_key == drug_key))

    async def _find_or_create_drug_from_dur(self, item: dict, prefix: str = "") -> Drug | None:
        """DUR 응답 행의 품목을 item_seq(없으면 이름)로 찾고, 없으면 그 행의 정보로 최소 Drug 레코드를
        만든다. 병용금기 행은 두 번째 품목의 키에 `MIXTURE_`가 붙으므로 `prefix`로 고른다.
        이름이 없는 행이면 None."""
        name = _clean(item.get(f"{prefix}ITEM_NAME"))
        if not name:
            return None
        seq = _clean(item.get(f"{prefix}ITEM_SEQ"))

        if seq and seq in self._drug_by_seq:
            return self._drug_by_seq[seq]

        if seq:
            drug = await self.db.scalar(select(Drug).where(Drug.item_seq == seq))
            if drug:
                self._drug_by_seq[seq] = drug
                return drug

        drug = await self._find_drug_by_name(name)
        if drug:
            if seq and not drug.item_seq:
                drug.item_seq = seq
            if seq:
                self._drug_by_seq[seq] = drug
            return drug

        drug = Drug(
            item_seq=seq or f"DUR_{_make_drug_key(name)}",
            item_name=name,
            simple_name=_make_simple_name(name),
            drug_key=_make_drug_key(name),
            entp_name=_clean(item.get(f"{prefix}ENTP_NAME")),
            main_item_ingr=_clean(item.get(f"{prefix}MAIN_INGR")),
            class_name=_clean(item.get(f"{prefix}CLASS_NAME")),
            etc_otc_name=_clean(item.get(f"{prefix}ETC_OTC_NAME")),
        )
        self.db.add(drug)
        await self.db.flush()
        if seq:
            self._drug_by_seq[seq] = drug
        return drug

    # ------------------------------------------------------------------ #
    # 행 upsert                                                            #
    # ------------------------------------------------------------------ #

    def _first_time(self, *key) -> bool:
        """이번 실행에서 처음 보는 키인가. 처음이면 기억해 둔다."""
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    async def _insert_once(
        self, model, key_cols: tuple[str, ...], values: dict, *, overwrite: bool = False,
    ) -> None:
        """`key_cols`가 같은 행이 없으면 넣는다. 이미 있으면 그대로 두고, `overwrite`면 나머지 열을
        원천 값으로 갱신한다. 유니크 제약이 같은 키에 걸려 있어야 한다."""
        if not self._first_time(model.__tablename__, *(values[c] for c in key_cols)):
            return
        stmt = pg_insert(model).values(**values)
        if overwrite:
            stmt = stmt.on_conflict_do_update(
                index_elements=list(key_cols),
                set_={c: stmt.excluded[c] for c in values if c not in key_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=list(key_cols))
        await self.db.execute(stmt)

    async def _upsert_drug_ingredient(
        self, drug_id, ingr_code: str | None, ingr_kor: str | None
    ) -> None:
        if not ingr_code:
            return
        await self._insert_once(
            DrugIngredient, ("drug_id", "ingr_code"),
            {"drug_id": drug_id, "ingr_code": ingr_code, "ingr_kor": ingr_kor, "source": "dur"},
        )
