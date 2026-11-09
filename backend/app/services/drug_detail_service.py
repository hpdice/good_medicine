"""식약처 의약품 제품 허가정보 상세(`getDrugPrdtPrmsnDtlInq06`)를 **배치로** 우리 DB에 적재한다.

e약은요(효능·용법·주의 소비자용 문구)는 전체 약의 13.8%만 다뤄서, 나머지 약(주로 전문의약품)은
설명 텍스트가 비고 성분 정보도 없었다. 허가정보 상세에는 모든 허가 품목의 효능효과(EE)·용법용량(UD)·
사용상의 주의사항(NB)과 주성분(`MAIN_ITEM_INGR`)이 있다.

**요청 경로(약 추가·약 상세 조회)에서는 부르지 않는다** — 건당 수 초가 걸려 사용자가 기다렸고, 이 프로젝트의 목적은
정제된 우리 DB를 만드는 것이라 앱은 DB만 읽는다. 적재는 `sync.py permit_detail`(`backfill_details`)이 맡는다:
`detail_fetched_at`이 NULL인 약만, 동시 N개로, 일일 한도 안에서(`--limit`) 받고 이어 받는다. 실패한 약은
`detail_fetched_at`을 안 찍어 다음 실행에서 다시 시도한다.

채우는 규칙(전부 "비어 있을 때만" — e약은요 값은 절대 덮어쓰지 않는다):
  EE → efcy_qesitm, UD → use_method_qesitm, NB → atpn_qesitm(전문 — 화면은 앱의 "더보기"가 접고,
  AI 프롬프트는 `ai_guide_service`가 필드당 상한으로 자른다),
  MAIN_ITEM_INGR → main_item_ingr + ingr_name,
  그리고 `drug_ingredients`에 없는 성분은 성분명으로 DUR 성분코드 해소(source='permit_detail').
DUR 성분코드(D…)와 허가정보 성분코드(M…)는 체계가 달라 코드로는 못 잇고 이름으로만 맺는다.
"""
import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.services.public_data_service.helpers import (
    _clean,
    _parse_main_ingr,
    make_ingredient_resolver,
    permit_doc_to_text,
)
from app.services.public_data_service.maintenance import (
    dur_ingredient_name_pairs,
    refresh_drugs_master_row,
)

DETAIL_TIMEOUT_SECONDS = 8.0
REALTIME_TIMEOUT_SECONDS = 4.0  # 요청 중 보충용 — 늦으면 기다리지 않고 DB 값만으로 진행한다
BATCH_RESERVE_DEFAULT = 1500    # 일일 한도(약 10,000건) 중 실시간 보충용으로 남겨 두는 호출 수

BACKGROUND_TIMEOUT_SECONDS = 40.0  # 요청 중 4초에 못 받은 약을 뒤에서 마저 받을 때의 대기

# 가장 최근 응답의 남은 호출 수(`x-ratelimit-remaining`) — 배치가 한도를 다 쓰지 않게 보는 용도
_quota: dict[str, int | None] = {"remaining": None}


def _detail_url() -> str:
    return f"{settings.DRUG_APPROVAL_API_URL}/getDrugPrdtPrmsnDtlInq06"


class DrugDetailService:
    def __init__(self, db: AsyncSession, timeout: float = DETAIL_TIMEOUT_SECONDS) -> None:
        self.db = db
        self._timeout = timeout

    async def ensure_detail(self, drug: Drug) -> bool:
        """아직 보강 안 한 약이면 상세 API를 한 번 불러 채운다. 새로 채웠으면 True.

        API 키가 없거나 호출이 실패하면 False — 예외를 올리지 않는다."""
        if drug.detail_fetched_at is not None or not settings.PUBLIC_DATA_API_KEY:
            return False
        item = await self._fetch(drug.item_seq)
        if item is None:
            return False
        await self._apply(drug, item)
        drug.detail_fetched_at = datetime.now(timezone.utc)
        await self.db.commit()
        # 통합 데이터셋도 바로 맞춘다. 실패해도 약 정보 적재는 이미 끝났으니 막지 않는다(다음 전체 구축 때 맞춰진다).
        try:
            await refresh_drugs_master_row(self.db, drug.id)
        except Exception:  # noqa: BLE001
            await self.db.rollback()
            logger.exception("drugs_master 행 갱신 실패 drug_id=%s", drug.id)
        return True

    async def _fetch(self, item_seq: str) -> dict | None:
        params = {
            "serviceKey": settings.PUBLIC_DATA_API_KEY, "type": "json",
            "pageNo": 1, "numOfRows": 1, "item_seq": item_seq,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(_detail_url(), params=params)
                resp.raise_for_status()
                remaining = resp.headers.get("x-ratelimit-remaining")
                if remaining and remaining.isdigit():
                    _quota["remaining"] = int(remaining)
                items = (resp.json().get("body") or {}).get("items") or []
        except Exception as e:  # noqa: BLE001 — 네트워크·형식 오류 전부 "이번엔 못 채움"
            logger.warning("허가정보 상세 조회 실패 item_seq=%s: %s", item_seq, type(e).__name__)
            return None
        # 조회 성공인데 결과가 0건이면 이 품목은 허가 DB에 없다 — 빈 dict로 "해봤음"을 남긴다.
        return items[0] if items else {}

    async def _apply(self, drug: Drug, item: dict) -> None:
        if not drug.efcy_qesitm:
            drug.efcy_qesitm = permit_doc_to_text(item.get("EE_DOC_DATA"))
        if not drug.use_method_qesitm:
            drug.use_method_qesitm = permit_doc_to_text(item.get("UD_DOC_DATA"))
        if not drug.atpn_qesitm:
            drug.atpn_qesitm = permit_doc_to_text(item.get("NB_DOC_DATA"))

        main_ingr = _clean(item.get("MAIN_ITEM_INGR"))
        if main_ingr and not drug.main_item_ingr:
            drug.main_item_ingr = main_ingr
            if not drug.ingr_name:
                drug.ingr_name = _parse_main_ingr(main_ingr) or None

        await self._resolve_ingredients(drug)

    async def _resolve_ingredients(self, drug: Drug) -> None:
        """성분명으로 DUR 성분코드를 맺는다(성분 단위 DUR 판정 대상이 됨). 이미 맺은 코드는 두고 **없는 코드만** 더한다 —
        복합제가 일부 성분만 맺혀 있으면(감기약에 아세트아미노펜이 빠진 경우) 그 성분의 판정을 놓치기 때문이다."""
        existing = {code for code in (await self.db.execute(
            select(DrugIngredient.ingr_code).where(DrugIngredient.drug_id == drug.id)
        )).scalars() if code}
        names = [i["kor"] for i in (drug.ingr_name or []) if i.get("kor")]
        if not names:
            return
        resolve = make_ingredient_resolver(await dur_ingredient_name_pairs(self.db))
        seen: set[str] = set(existing)
        for name in names:
            code = resolve(name)
            if code and code not in seen:
                seen.add(code)
                self.db.add(DrugIngredient(
                    drug_id=drug.id, ingr_code=code, ingr_kor=name, source="permit_detail",
                ))


# 우선순위: 설명 텍스트가 없는 약 → DUR 성분이 맺힌(판정 가능) 약 → 일반의약품 → 이름순. 한도(--limit)가 있어
# 앞쪽부터 받는다. (`drugs_master`가 아직 없는 DB에서도 돌도록 `drug_ingredients`로 판정 가능 여부를 본다.)
_BACKFILL_ORDER_SQL = """
SELECT d.id FROM drugs d
WHERE d.detail_fetched_at IS NULL AND d.item_seq IS NOT NULL
ORDER BY (COALESCE(d.efcy_qesitm, '') = '') DESC,
         EXISTS (SELECT 1 FROM drug_ingredients di WHERE di.drug_id = d.id AND di.ingr_code IS NOT NULL) DESC,
         (d.etc_otc_name = '일반의약품') DESC NULLS LAST,
         d.item_name
LIMIT :n
"""


async def backfill_details(
    session_factory,
    limit: int,
    concurrency: int = 8,
    max_consecutive_failures: int = 30,
    log: Callable[[str], None] = print,
    timeout: float = 40.0,
    reserve: int = BATCH_RESERVE_DEFAULT,
) -> dict:
    """허가정보 상세를 아직 안 받은 약을 우선순위대로 최대 `limit`건 받아 DB에 적재한다(배치 전용).

    약마다 자기 세션으로 `ensure_detail`을 부른다. 연속 `max_consecutive_failures`번 실패하면(한도 초과·장애로 보고)
    멈추고 `stopped=True`를 돌려준다 — 실패한 약은 표시하지 않아 다음 실행이 이어 받는다.
    배치는 사람이 기다리지 않으므로 요청당 대기(`timeout`)를 넉넉히 둔다 — 타임아웃도 일일 한도(약 10,000건)에서 한 번으로
    세어져, 짧게 두면 한도만 낭비한다. 남은 일일 호출이 `reserve` 아래로 내려가면 멈춘다(`quota_low`) — 앱이 실시간으로 보충할 호출을 남겨 두려는 것이다.
    돌려주는 값: {candidates, done, failed, stopped, quota_low}."""
    if not settings.PUBLIC_DATA_API_KEY:
        log("PUBLIC_DATA_API_KEY가 없습니다.")
        return {"candidates": 0, "done": 0, "failed": 0, "stopped": True, "quota_low": False}

    async with session_factory() as db:
        ids = [r[0] for r in (await db.execute(text(_BACKFILL_ORDER_SQL), {"n": limit})).all()]
    total = len(ids)
    log(f"허가정보 상세 적재 대상 {total:,}건 (동시 {concurrency}개)")

    sem = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()
    state = {"done": 0, "failed": 0, "streak": 0, "quota_low": False}

    async def work(drug_id) -> None:
        async with sem:
            if stop.is_set():
                return
            ok = False
            try:
                async with session_factory() as s:
                    drug = await s.get(Drug, drug_id)
                    ok = bool(drug) and await DrugDetailService(s, timeout=timeout).ensure_detail(drug)
            except Exception:  # noqa: BLE001 — 한 건의 오류가 배치를 멈추지 않게
                logger.exception("허가정보 상세 적재 중 오류 drug_id=%s", drug_id)
            if ok:
                state["done"] += 1
                state["streak"] = 0
                remaining = _quota["remaining"]
                if remaining is not None and remaining < reserve:
                    state["quota_low"] = True
                    stop.set()
            else:
                state["failed"] += 1
                state["streak"] += 1
                if state["streak"] >= max_consecutive_failures:
                    stop.set()
            n = state["done"] + state["failed"]
            if n % 200 == 0:
                log(f"  진행 {n:,}/{total:,} — 성공 {state['done']:,}, 실패 {state['failed']:,}")

    # 첫 건을 혼자 먼저 처리해 남은 호출 수를 확인한다 — 이미 예약분 아래면 더 부르지 않는다.
    if ids:
        await work(ids[0])
        if not stop.is_set():
            await asyncio.gather(*(work(i) for i in ids[1:]))
    return {"candidates": total, "done": state["done"], "failed": state["failed"], "stopped": stop.is_set(),
            "quota_low": state["quota_low"]}


# 백그라운드로 도는 작업을 붙잡아 둔다(참조가 없으면 끝나기 전에 수거될 수 있다).
_background: set[asyncio.Task] = set()


def schedule_detail_completion(drug_id, bind) -> None:
    """요청 중 짧은 제한(4초) 안에 못 받은 약을 응답 뒤에 마저 받아 DB에 저장한다.

    응답은 기다리지 않는다 — 앱은 DB 값을 읽으니, 받아 오는 대로 다음 조회부터 보인다(성분 연결도 같이)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)

    async def run() -> None:
        try:
            async with factory() as s:
                drug = await s.get(Drug, drug_id)
                if drug is not None:
                    await DrugDetailService(s, timeout=BACKGROUND_TIMEOUT_SECONDS).ensure_detail(drug)
        except Exception:  # noqa: BLE001 — 부가 작업, 실패해도 다음 배치가 받는다
            logger.exception("허가정보 상세 백그라운드 적재 실패 drug_id=%s", drug_id)

    task = asyncio.create_task(run())
    _background.add(task)
    task.add_done_callback(_background.discard)
