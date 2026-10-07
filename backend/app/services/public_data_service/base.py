"""동기화 서비스 공통 기반 — HTTP 페이지 조회·재시도, Drug 레코드 확보,
성분 upsert처럼 여러 소스가 공유하는 인프라만 담는다. 특정 DUR 판정 규칙
(병용금기·효능군중복·연령대금기) upsert는 dur_sync.py로 분리."""
import asyncio
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient

from . import raw_store
from .helpers import _make_drug_key, _make_simple_name


class _SyncBase:
    PAGE_SIZE = 100

    def __init__(self, db: AsyncSession, progress_cb=None) -> None:
        self.db = db
        self._api_key = settings.PUBLIC_DATA_API_KEY
        self._progress_cb = progress_cb
        # 성분 sweep에서 (drug_id, ingr_code)·(code_a, code_b)가 수천 번 재등장하므로
        # run 내 in-memory 캐시로 중복 upsert의 DB 왕복을 건너뛴다.
        self._seen_drug_ingr: set[tuple] = set()
        self._seen_ingr_contra: set[tuple] = set()
        self._seen_ingr_effect: set[tuple] = set()
        self._seen_ingr_age: set[tuple] = set()
        # 이번 실행에서 금기 사유 문장이 바뀌어 갱신된 성분쌍 규칙 수(로그·검증용)
        self._updated_ingr_contra = 0
        # item_seq -> Drug — 같은 품목이 병용금기 수십~수백 쌍에 반복 등장하므로
        # (예: 흔한 진통제 한 품목이 수백 개 다른 품목과 쌍을 이룸) 캐시 없이는
        # _find_or_create_drug_from_dur가 매번 DB 왕복한다(796,842행 sweep에서
        # 실측: 이게 가장 큰 시간 비중을 차지함).
        self._drug_by_seq: dict[str, Drug] = {}
        # 원본 응답 보관(bronze). replay_snapshot이 있으면 API 대신 저장된 파일에서 읽는다
        # ("latest" = 엔드포인트별 가장 최근 스냅샷). 재파싱 시엔 새로 저장하지 않는다.
        self.replay_snapshot: str | None = None
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
        if snapshot == "latest":
            snapshot = raw_store.latest_snapshot(endpoint)
            if snapshot is None:
                logger.error(f"replay할 raw 스냅샷이 없음: {endpoint}")
                return None
        return raw_store.load_page(endpoint, snapshot, int(params["pageNo"]))

    # ------------------------------------------------------------------ #
    # 공통 페이지네이션 루프 — 단순형(3곳이 쓰던 걸 통합) /                    #
    #                        다중 엔드포인트형(2곳이 쓰던 걸 통합)            #
    # ------------------------------------------------------------------ #

    async def _run_simple_paginated_sync(
        self, url: str, item_handler, source: str, log_label: str, page_size: int | None = None,
    ) -> int:
        """단일 엔드포인트를 totalCount까지 순회하며 `item_handler(item)`을 호출한다.
        `_sync_drug_overview`/`_sync_efcy_dplct`/`sync_drug_approval`이 각자 복붙해
        갖고 있던 거의 동일한 루프를 추출한 것(로직 변경 없음). `page_size`는 검증된
        호출부만 기본값(100)보다 키워서 넘긴다 — 서비스마다 상한이 달라서 전역으로
        올리면 안전하지 않다(실측: DUR 계열은 500까지 됨, 그 이상은 빈 응답)."""
        size = page_size or self.PAGE_SIZE
        count = 0
        page = 1
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"serviceKey": self._api_key, "pageNo": page, "numOfRows": size, "type": "json"}
                data = await self._fetch_page(client, url, params)
                if data is None:
                    # _fetch_page 가 재시도를 다 쓴 상태. 이전엔 page += 1 로 건너뛰어 그 페이지가
                    # 빠진 채 "완료"됐고, API 가 아예 죽으면 끝없이 페이지 번호만 올리며 돌았다.
                    # 중단한다 — 이 루프의 적재는 멱등(upsert)이라 재실행하면 처음부터 안전하게 다시 받는다.
                    raise RuntimeError(
                        f"{log_label} page {page} 요청 실패(재시도 소진) — 건너뛰지 않고 중단. 재실행 필요."
                    )

                items = data.get("body", {}).get("items", [])
                if not items:
                    break

                for item in items:
                    await item_handler(item)
                    count += 1

                await self.db.commit()
                total = data.get("body", {}).get("totalCount", 0)
                logger.info(f"Synced {log_label} page {page} ({count}/{total})")
                await self._emit(source=source, page=page, count=count, total=total)

                if count >= total or len(items) < size:
                    break
                page += 1
                await asyncio.sleep(0.5)

        return count

    async def _run_multi_endpoint_sync(
        self, ops: dict, item_handler, *, error_label: str, source_prefix: str,
        retry_hint: str, page_size: int | None = None,
    ) -> int:
        """`ops`: {label: (엔드포인트 op, item_handler에 넘길 부가값)}을 순회하며 각각
        totalCount까지 페이지를 돈다. 페이지 요청이 재시도 끝에 실패하면 건너뛰지 않고
        RuntimeError. `sync_dur_age_caution`/`sync_dur_extra_ingredient_codes`가
        각자 갖고 있던 거의 동일한 루프를 추출한 것(로직 변경 없음)."""
        size = page_size or self.PAGE_SIZE
        processed = 0
        for label, (op, extra) in ops.items():
            url = f"{settings.DUR_PRODUCT_API_URL}/{op}"
            page = 1
            ep_count = 0
            async with httpx.AsyncClient(timeout=30) as client:
                while True:
                    params = {
                        "serviceKey": self._api_key, "pageNo": page,
                        "numOfRows": size, "type": "json",
                    }
                    data = await self._fetch_page(client, url, params)
                    if data is None:
                        # 이전엔 연속 3회가 아니면 그 페이지를 건너뛰고 계속했다(조용한 누락).
                        raise RuntimeError(
                            f"{error_label} [{label}] page {page} 요청 실패(재시도 소진) — 건너뛰지 않고 중단. "
                            f"할당량 초과일 수 있음 — 리셋 후 `{retry_hint}` 재실행."
                        )

                    items = data.get("body", {}).get("items", [])
                    if not items:
                        break

                    for item in items:
                        await item_handler(item, extra)
                        ep_count += 1
                        processed += 1

                    await self.db.commit()
                    total = data.get("body", {}).get("totalCount", 0)
                    logger.info(f"{error_label} [{label}] page {page} ({ep_count}/{total})")
                    await self._emit(source=f"{source_prefix}:{label}", page=page, count=ep_count, total=total)

                    if len(items) < size:
                        break
                    page += 1
                    await asyncio.sleep(0.5)

        return processed

    # ------------------------------------------------------------------ #
    # Drug 레코드 확보 — 여러 sync가 공유                                    #
    # ------------------------------------------------------------------ #

    async def _find_drug_by_name(self, name: str) -> Drug | None:
        drug_key = _make_drug_key(name)
        return await self.db.scalar(select(Drug).where(Drug.drug_key == drug_key))

    async def _find_or_create_drug_from_dur(
        self,
        seq: str | None,
        name: str,
        entp: str | None,
        main_ingr: str | None,
        permit_date_str: str | None,
        class_name: str | None,
        etc_otc_name: str | None,
    ) -> Drug:
        """item_seq로 조회하고 없으면 DUR 데이터로 최소 Drug 레코드를 생성한다."""
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

        permit_date: date | None = None
        if permit_date_str and len(permit_date_str) == 8:
            try:
                permit_date = date(int(permit_date_str[:4]), int(permit_date_str[4:6]), int(permit_date_str[6:]))
            except ValueError:
                pass

        drug = Drug(
            item_seq=seq or f"DUR_{_make_drug_key(name)}",
            item_name=name,
            simple_name=_make_simple_name(name),
            drug_key=_make_drug_key(name),
            entp_name=entp,
            main_item_ingr=main_ingr,
            item_permit_date=permit_date,
            class_name=class_name,
            etc_otc_name=etc_otc_name,
        )
        self.db.add(drug)
        await self.db.flush()
        if seq:
            self._drug_by_seq[seq] = drug
        return drug

    async def _upsert_drug_ingredient(
        self, drug_id, ingr_code: str | None, ingr_kor: str | None
    ) -> None:
        if not ingr_code:
            return
        key = (drug_id, ingr_code)
        if key in self._seen_drug_ingr:
            return
        self._seen_drug_ingr.add(key)

        existing = await self.db.scalar(
            select(DrugIngredient).where(
                DrugIngredient.drug_id == drug_id,
                DrugIngredient.ingr_code == ingr_code,
            )
        )
        if existing:
            return
        self.db.add(DrugIngredient(
            drug_id=drug_id, ingr_code=ingr_code, ingr_kor=ingr_kor, source="dur",
        ))
