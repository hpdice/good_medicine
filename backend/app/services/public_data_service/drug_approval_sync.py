"""의약품 제품 허가정보(DrugPrdtPrmsnInfoService07)."""
import re

from sqlalchemy import select

from app.config import settings
from app.models.drug import Drug

from .base import _SyncBase
from .helpers import _clean, _make_drug_key, _make_simple_name, _parse_permit_date


class DrugApprovalSyncMixin(_SyncBase):
    async def sync_drug_approval(self) -> int:
        url = f"{settings.DRUG_APPROVAL_API_URL}/getDrugPrdtPrmsnInq07"
        return await self._sync_endpoint(
            url, self._upsert_drug_from_approval, source="approval", label="drug approval",
        )

    async def _upsert_drug_from_approval(self, item: dict) -> None:
        if _clean(item.get("CANCEL_NAME")) != "정상":
            return

        raw_seq = _clean(item.get("ITEM_SEQ"))
        raw_name = _clean(item.get("ITEM_NAME"))
        if not raw_seq or not raw_name:
            return

        drug = await self.db.scalar(select(Drug).where(Drug.item_seq == raw_seq))

        permit_date = _parse_permit_date(_clean(item.get("ITEM_PERMIT_DATE")))

        prduct_type_raw = _clean(item.get("PRDUCT_TYPE")) or ""
        class_name = re.sub(r'^\[\d+\]', '', prduct_type_raw).strip() or None

        if drug:
            if not drug.simple_name:
                drug.simple_name = _make_simple_name(raw_name)
            if not drug.item_permit_date:
                drug.item_permit_date = permit_date
            if not drug.class_name:
                drug.class_name = class_name
            if not drug.etc_otc_name:
                drug.etc_otc_name = _clean(item.get("SPCLTY_PBLC"))
            return

        drug = Drug(
            item_seq=raw_seq,
            item_name=raw_name,
            simple_name=_make_simple_name(raw_name),
            drug_key=_make_drug_key(raw_name),
            entp_name=_clean(item.get("ENTP_NAME")),
            item_permit_date=permit_date,
            class_name=class_name,
            etc_otc_name=_clean(item.get("SPCLTY_PBLC")),
        )
        self.db.add(drug)
