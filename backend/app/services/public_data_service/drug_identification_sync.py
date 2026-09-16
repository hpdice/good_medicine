"""의약품 낱알식별 정보(MdcinGrnIdntfcInfoService01) — drug_shape·color·각인 보강.
XML 응답이라 다른 소스와 달리 `_fetch_page`(JSON 전용)를 쓰지 않고 자체 루프를 갖는다."""
import asyncio
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import select

from app.config import settings
from app.core.logging import logger
from app.models.drug import Drug

from .helpers import _clean, _make_drug_key


class DrugIdentificationSyncMixin:
    async def _sync_drug_identification(self) -> int:
        url = f"{settings.DRUG_IDENTIFY_API_URL}/getMdcinGrnIdntfcInfoList03"
        count = 0
        page = 1

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"serviceKey": self._api_key, "pageNo": page, "numOfRows": self.PAGE_SIZE}
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    root = ET.fromstring(resp.text)
                except Exception as e:
                    logger.warning(f"identification page {page} error: {e}")
                    page += 1
                    continue

                total_el = root.find(".//totalCount")
                total = int(total_el.text) if total_el is not None and total_el.text else 0

                items_el = root.find(".//items")
                items = list(items_el) if items_el is not None else []

                if not items:
                    break

                for item_el in items:
                    item = {child.tag: child.text for child in item_el}
                    await self._update_drug_identification(item)
                    count += 1

                await self.db.commit()
                logger.info(f"Synced drug identification page {page} ({count}/{total})")
                await self._emit(source="identification", page=page, count=count, total=total)

                if count >= total or len(items) < self.PAGE_SIZE:
                    break
                page += 1
                await asyncio.sleep(0.5)

        return count

    async def _update_drug_identification(self, item: dict) -> None:
        item_seq = _clean(item.get("ITEM_SEQ"))
        drug = None

        if item_seq:
            drug = await self.db.scalar(select(Drug).where(Drug.item_seq == item_seq))

        if not drug:
            item_name = _clean(item.get("ITEM_NAME"))
            if item_name:
                drug_key = _make_drug_key(item_name)
                drug = await self.db.scalar(select(Drug).where(Drug.drug_key == drug_key))

        if not drug:
            return

        drug.drug_shape = _clean(item.get("DRUG_SHAPE"))
        drug.color_class1 = _clean(item.get("COLOR_CLASS1"))
        drug.print_front = _clean(item.get("PRINT_FRONT"))
        drug.print_back = _clean(item.get("PRINT_BACK"))
        if not drug.item_image:
            drug.item_image = _clean(item.get("ITEM_IMAGE"))
