"""식약처 의약품 제품 허가정보 상세(`getDrugPrdtPrmsnDtlInq06`)로 약 한 건을 온디맨드 보강.

e약은요(효능·용법·주의 소비자용 문구)는 전체 약의 13.7%만 다뤄서, 나머지 약(주로 전문의약품)은
복약함에 담아도 설명 텍스트가 비고 성분 정보도 없었다. 허가정보 상세에는 모든 허가 품목의
효능효과(EE)·용법용량(UD)·사용상의 주의사항(NB)과 주성분(`MAIN_ITEM_INGR`)이 있다.

전체 일괄 동기화가 아니라 **사용자가 약을 복약함에 담을 때 그 약 하나만** 부른다 — 쓰는 약만
채워지고, 월간 동기화·API 한도에 부담이 없다. 실패해도 약 추가는 막지 않는다(호출부가 예외를
삼키고, `detail_fetched_at`을 안 찍어 다음에 다시 시도한다).

채우는 규칙(전부 "비어 있을 때만" — e약은요 값은 절대 덮어쓰지 않는다):
  EE → efcy_qesitm, UD → use_method_qesitm, NB → atpn_qesitm(길이 제한, 아래),
  MAIN_ITEM_INGR → main_item_ingr + ingr_name,
  그리고 `drug_ingredients` 행이 없으면 성분명으로 DUR 성분코드 해소(source='permit_detail').
DUR 성분코드(D…)와 허가정보 성분코드(M…)는 체계가 달라 코드로는 못 잇고 이름으로만 맺는다.
"""
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
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

DETAIL_TIMEOUT_SECONDS = 8.0
# 사용상의 주의사항 전문은 수십 KB가 되기도 한다 — 복약함 카드·AI 설명 프롬프트에 그대로 넣기엔
# 크므로 금기 등 앞쪽 항목 위주로 이 길이까지만 담는다.
CAUTION_MAX_CHARS = 1500


def _detail_url() -> str:
    return f"{settings.DRUG_APPROVAL_API_URL}/getDrugPrdtPrmsnDtlInq06"


class DrugDetailService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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
        return True

    async def _fetch(self, item_seq: str) -> dict | None:
        params = {
            "serviceKey": settings.PUBLIC_DATA_API_KEY, "type": "json",
            "pageNo": 1, "numOfRows": 1, "item_seq": item_seq,
        }
        try:
            async with httpx.AsyncClient(timeout=DETAIL_TIMEOUT_SECONDS) as client:
                resp = await client.get(_detail_url(), params=params)
                resp.raise_for_status()
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
            drug.atpn_qesitm = permit_doc_to_text(item.get("NB_DOC_DATA"), max_chars=CAUTION_MAX_CHARS)

        main_ingr = _clean(item.get("MAIN_ITEM_INGR"))
        if main_ingr and not drug.main_item_ingr:
            drug.main_item_ingr = main_ingr
            if not drug.ingr_name:
                drug.ingr_name = _parse_main_ingr(main_ingr) or None

        await self._resolve_ingredients(drug)

    async def _resolve_ingredients(self, drug: Drug) -> None:
        """DUR 성분코드가 한 건도 없는 약만, 성분명으로 코드를 맺는다(성분 단위 DUR 판정 대상이 됨)."""
        has_rows = await self.db.scalar(
            select(DrugIngredient.id).where(DrugIngredient.drug_id == drug.id).limit(1)
        )
        if has_rows is not None:
            return
        names = [i["kor"] for i in (drug.ingr_name or []) if i.get("kor")]
        if not names:
            return
        known = await self.db.execute(
            select(DrugIngredient.ingr_kor, DrugIngredient.ingr_code)
            .where(DrugIngredient.ingr_code.isnot(None), DrugIngredient.ingr_kor.isnot(None))
            .distinct()
        )
        resolve = make_ingredient_resolver(known.all())
        seen: set[str] = set()
        for name in names:
            code = resolve(name)
            if code and code not in seen:
                seen.add(code)
                self.db.add(DrugIngredient(
                    drug_id=drug.id, ingr_code=code, ingr_kor=name, source="permit_detail",
                ))
