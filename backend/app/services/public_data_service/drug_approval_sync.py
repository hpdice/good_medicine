"""의약품 제품 허가정보(DrugPrdtPrmsnInfoService07)."""
import re
from datetime import date

from sqlalchemy import select

from app.config import settings
from app.models.drug import Drug

from .helpers import _clean, _make_drug_key, _make_simple_name


class DrugApprovalSyncMixin:
    async def sync_drug_approval(self) -> int:
        url = f"{settings.DRUG_APPROVAL_API_URL}/getDrugPrdtPrmsnInq07"
        return await self._run_simple_paginated_sync(
            url, self._upsert_drug_from_approval, source="approval", log_label="drug approval",
        )

    async def _upsert_drug_from_approval(self, item: dict) -> None:
        if _clean(item.get("CANCEL_NAME")) != "정상":
            return

        item_seq = _clean(item.get("ITEM_SEQ"))
        item_name = _clean(item.get("ITEM_NAME"))
        if not item_seq or not item_name:
            return

        drug = await self.db.scalar(select(Drug).where(Drug.item_seq == item_seq))

        permit_date: date | None = None
        permit_date_str = _clean(item.get("ITEM_PERMIT_DATE"))
        if permit_date_str and len(permit_date_str) == 8:
            try:
                permit_date = date(int(permit_date_str[:4]), int(permit_date_str[4:6]), int(permit_date_str[6:]))
            except ValueError:
                pass

        prduct_type_raw = _clean(item.get("PRDUCT_TYPE")) or ""
        class_name = re.sub(r'^\[\d+\]', '', prduct_type_raw).strip() or None

        if drug:
            if not drug.simple_name:
                drug.simple_name = _make_simple_name(item_name)
            if not drug.item_image:
                drug.item_image = _clean(item.get("BIG_PRDT_IMG_URL"))
            if not drug.item_permit_date:
                drug.item_permit_date = permit_date
            if not drug.class_name:
                drug.class_name = class_name
            if not drug.etc_otc_name:
                drug.etc_otc_name = _clean(item.get("SPCLTY_PBLC"))
            return

        drug = Drug(
            item_seq=item_seq,
            item_name=item_name,
            simple_name=_make_simple_name(item_name),
            drug_key=_make_drug_key(item_name),
            entp_name=_clean(item.get("ENTP_NAME")),
            item_permit_date=permit_date,
            class_name=class_name,
            etc_otc_name=_clean(item.get("SPCLTY_PBLC")),
            item_image=_clean(item.get("BIG_PRDT_IMG_URL")),
        )
        self.db.add(drug)
