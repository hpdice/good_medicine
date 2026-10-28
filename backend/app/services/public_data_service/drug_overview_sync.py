"""의약품개요정보(e약은요, DrbEasyDrugInfoService) — drugs 테이블 기본 데이터."""
from sqlalchemy import select

from app.config import settings
from app.models.drug import Drug

from .base import _SyncBase
from .helpers import _clean, _make_drug_key, _make_simple_name, _parse_ingredients


class DrugOverviewSyncMixin(_SyncBase):
    async def _sync_drug_overview(self) -> int:
        url = f"{settings.DRUG_OVERVIEW_API_URL}/getDrbEasyDrugList"
        return await self._sync_endpoint(
            url, self._upsert_drug_from_overview, source="overview", label="drug overview",
        )

    async def _upsert_drug_from_overview(self, item: dict) -> None:
        raw_seq = _clean(item.get("itemSeq"))
        raw_name = _clean(item.get("itemName"))
        if not raw_seq or not raw_name:
            return

        normalized_key = _make_drug_key(raw_name)

        drug = await self.db.scalar(select(Drug).where(Drug.item_seq == raw_seq))
        if not drug:
            drug = Drug(item_seq=raw_seq)
            self.db.add(drug)

        drug.drug_key = normalized_key
        drug.item_name = raw_name
        drug.simple_name = _make_simple_name(raw_name)
        drug.entp_name = _clean(item.get("entpName"))
        drug.efcy_qesitm = _clean(item.get("efcyQesitm"))
        drug.use_method_qesitm = _clean(item.get("useMethodQesitm"))
        drug.atpn_warn_qesitm = _clean(item.get("atpnWarnQesitm"))
        drug.atpn_qesitm = _clean(item.get("atpnQesitm"))
        drug.intrc_qesitm = _clean(item.get("intrcQesitm"))
        drug.se_qesitm = _clean(item.get("seQesitm"))
        drug.deposit_method_qesitm = _clean(item.get("depositMethodQesitm"))
        drug.class_name = _clean(item.get("className"))

        ingr_raw = _clean(item.get("mainItemIngr"))
        drug.main_item_ingr = ingr_raw
        if ingr_raw:
            drug.ingr_name = _parse_ingredients(ingr_raw)
