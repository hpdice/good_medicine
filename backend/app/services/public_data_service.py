"""
공공데이터포털 의약품 API 통합 서비스.
- 의약품개요정보(e약은요): DrbEasyDrugInfoService
- 의약품안전사용서비스(DUR) 품목정보: DURPrdlstInfoService03
- 의약품안전사용서비스(DUR) 성분정보: DURIrdntInfoService
- 의약품 낱알식별 정보: MdcinGrnIdntfcInfoService01
"""
import asyncio
import re
from datetime import date
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.models.drug import Drug
from app.models.drug_effect_group import DrugEffectGroup
from app.models.drug_interaction import DrugInteraction


class PublicDataService:
    PAGE_SIZE = 100

    def __init__(self, db: AsyncSession, progress_cb=None) -> None:
        self.db = db
        self._api_key = settings.PUBLIC_DATA_API_KEY
        self._progress_cb = progress_cb

    async def _emit(self, **kwargs) -> None:
        if self._progress_cb:
            await self._progress_cb(kwargs)

    async def _fetch_page(self, client: httpx.AsyncClient, url: str, params: dict, retries: int = 5) -> dict | None:
        """페이지 요청. 429는 60초 대기 후 재시도, 그 외 에러는 지수 백오프."""
        for attempt in range(retries):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
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

    async def sync_all(self) -> dict:
        """5개 공공데이터 소스를 순서대로 동기화한다."""
        overview_count = await self._sync_drug_overview()
        dur_pairs_count = await self._sync_dur_contraindications()
        efcy_dplct_count = await self._sync_efcy_dplct()
        dur_ingr_count = await self._sync_dur_ingredients()
        identify_count = await self._sync_drug_identification()
        return {
            "drug_overview": overview_count,
            "dur_contraindications": dur_pairs_count,
            "efcy_dplct": efcy_dplct_count,
            "dur_ingredients": dur_ingr_count,
            "drug_identification": identify_count,
        }

    # ------------------------------------------------------------------ #
    # e약은요 — drugs 테이블 기본 데이터                                    #
    # ------------------------------------------------------------------ #

    async def _sync_drug_overview(self) -> int:
        url = f"{settings.DRUG_OVERVIEW_API_URL}/getDrbEasyDrugList"
        count = 0
        page = 1

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"serviceKey": self._api_key, "pageNo": page, "numOfRows": self.PAGE_SIZE, "type": "json"}
                data = await self._fetch_page(client, url, params)
                if data is None:
                    page += 1
                    continue

                items = data.get("body", {}).get("items", [])
                if not items:
                    break

                for item in items:
                    await self._upsert_drug_from_overview(item)
                    count += 1

                await self.db.commit()
                total = data.get("body", {}).get("totalCount", 0)
                logger.info(f"Synced drug overview page {page} ({count}/{total})")
                await self._emit(source="overview", page=page, count=count, total=total)

                if count >= total or len(items) < self.PAGE_SIZE:
                    break
                page += 1
                await asyncio.sleep(0.5)

        return count

    async def _upsert_drug_from_overview(self, item: dict) -> None:
        item_seq = _clean(item.get("itemSeq"))
        item_name = _clean(item.get("itemName"))
        if not item_seq or not item_name:
            return

        drug_key = _make_drug_key(item_name)

        drug = await self.db.scalar(select(Drug).where(Drug.item_seq == item_seq))
        if not drug:
            drug = Drug(item_seq=item_seq)
            self.db.add(drug)

        drug.drug_key = drug_key
        drug.item_name = item_name
        drug.simple_name = _make_simple_name(item_name)
        drug.entp_name = _clean(item.get("entpName"))
        drug.efcy_qesitm = _clean(item.get("efcyQesitm"))
        drug.use_method_qesitm = _clean(item.get("useMethodQesitm"))
        drug.atpn_warn_qesitm = _clean(item.get("atpnWarnQesitm"))
        drug.atpn_qesitm = _clean(item.get("atpnQesitm"))
        drug.intrc_qesitm = _clean(item.get("intrcQesitm"))
        drug.se_qesitm = _clean(item.get("seQesitm"))
        drug.deposit_method_qesitm = _clean(item.get("depositMethodQesitm"))
        drug.item_image = _clean(item.get("itemImage"))
        drug.class_name = _clean(item.get("className"))

        ingr_raw = _clean(item.get("mainItemIngr"))
        drug.main_item_ingr = ingr_raw
        if ingr_raw:
            drug.ingr_name = _parse_ingredients(ingr_raw)

    # ------------------------------------------------------------------ #
    # DUR 품목정보 — drug_interactions 병용금기 쌍                          #
    # ------------------------------------------------------------------ #

    CHECKPOINT_FILE = "/tmp/dur_contraindications_checkpoint.txt"

    def _load_checkpoint(self) -> int:
        try:
            with open(self.CHECKPOINT_FILE) as f:
                return int(f.read().strip())
        except Exception:
            return 1

    def _save_checkpoint(self, page: int) -> None:
        try:
            with open(self.CHECKPOINT_FILE, "w") as f:
                f.write(str(page))
        except Exception:
            pass

    def _clear_checkpoint(self) -> None:
        try:
            import os as _os
            _os.remove(self.CHECKPOINT_FILE)
        except Exception:
            pass

    async def _sync_dur_contraindications(self) -> int:
        url = f"{settings.DUR_PRODUCT_API_URL}/getUsjntTabooInfoList03"
        count = 0
        page = self._load_checkpoint()

        if page > 1:
            logger.info(f"DUR 병용금기 체크포인트에서 재시작: 페이지 {page}")

        consecutive_failures = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"serviceKey": self._api_key, "pageNo": page, "numOfRows": self.PAGE_SIZE, "type": "json"}
                data = await self._fetch_page(client, url, params)
                if data is None:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        raise RuntimeError(f"연속 {consecutive_failures}회 페이지 요청 실패 — 일일 할당량 초과로 중단. 체크포인트: 페이지 {page}")
                    page += 1
                    continue
                consecutive_failures = 0

                items = data.get("body", {}).get("items", [])
                if not items:
                    break

                for item in items:
                    await self._upsert_dur_contraindication(item)
                    count += 1

                await self.db.commit()
                self._save_checkpoint(page)

                total = data.get("body", {}).get("totalCount", 0)
                logger.info(f"Synced DUR contraindications page {page} ({count}/{total})")
                await self._emit(source="dur_contraindications", page=page, count=count, total=total)

                if len(items) < self.PAGE_SIZE:
                    break
                page += 1
                await asyncio.sleep(1.5)

        self._clear_checkpoint()
        return count

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
        if seq:
            drug = await self.db.scalar(select(Drug).where(Drug.item_seq == seq))
            if drug:
                return drug

        drug = await self._find_drug_by_name(name)
        if drug:
            if seq and not drug.item_seq:
                drug.item_seq = seq
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
        return drug

    async def _upsert_dur_contraindication(self, item: dict) -> None:
        seq_a  = _clean(item.get("ITEM_SEQ"))
        seq_b  = _clean(item.get("MIXTURE_ITEM_SEQ"))
        name_a = _clean(item.get("ITEM_NAME") or item.get("itemName"))
        name_b = _clean(item.get("MIXTURE_ITEM_NAME") or item.get("mixtureItemName"))
        mechanism = _clean(item.get("PROHBT_CONTENT") or item.get("prohbtContent"))

        if not name_a or not name_b:
            return

        drug_a = await self._find_or_create_drug_from_dur(
            seq=seq_a, name=name_a,
            entp=_clean(item.get("ENTP_NAME")),
            main_ingr=_clean(item.get("MAIN_INGR")),
            permit_date_str=_clean(item.get("ITEM_PERMIT_DATE")),
            class_name=_clean(item.get("CLASS_NAME")),
            etc_otc_name=_clean(item.get("ETC_OTC_NAME")),
        )
        drug_b = await self._find_or_create_drug_from_dur(
            seq=seq_b, name=name_b,
            entp=_clean(item.get("MIXTURE_ENTP_NAME")),
            main_ingr=_clean(item.get("MIXTURE_MAIN_INGR")),
            permit_date_str=_clean(item.get("MIXTURE_ITEM_PERMIT_DATE")),
            class_name=_clean(item.get("MIXTURE_CLASS_NAME")),
            etc_otc_name=_clean(item.get("MIXTURE_ETC_OTC_NAME")),
        )

        # 방향 무관 조회이므로 (A,B)·(B,A) 둘 중 하나만 저장하면 충분하다.
        # 모든 조회 쪽(get_interactions_for_pair의 OR, get_interactions_for_drug_list의
        # in() 교집합)이 이미 방향을 가리지 않으므로 양방향을 모두 저장하면
        # quick-check 결과에 동일 쌍이 두 번 나타나는 중복이 발생한다.
        existing = await self.db.scalar(
            select(DrugInteraction).where(
                or_(
                    (DrugInteraction.drug1_id == drug_a.id) & (DrugInteraction.drug2_id == drug_b.id),
                    (DrugInteraction.drug1_id == drug_b.id) & (DrugInteraction.drug2_id == drug_a.id),
                ),
                DrugInteraction.interaction_type == "contraindicated",
            )
        )
        if existing:
            return

        interaction = DrugInteraction(
            drug1_id=drug_a.id,
            drug2_id=drug_b.id,
            interaction_type="contraindicated",
            mechanism=mechanism,
        )
        self.db.add(interaction)

    # ------------------------------------------------------------------ #
    # DUR 품목정보 — 효능군중복주의 (병용금기가 아닌 '주의' 등급)              #
    # ------------------------------------------------------------------ #

    async def _sync_efcy_dplct(self) -> int:
        url = f"{settings.DUR_PRODUCT_API_URL}/getEfcyDplctInfoList03"
        count = 0
        page = 1

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"serviceKey": self._api_key, "pageNo": page, "numOfRows": self.PAGE_SIZE, "type": "json"}
                data = await self._fetch_page(client, url, params)
                if data is None:
                    page += 1
                    continue

                items = data.get("body", {}).get("items", [])
                if not items:
                    break

                for item in items:
                    await self._upsert_efcy_dplct(item)
                    count += 1

                await self.db.commit()
                total = data.get("body", {}).get("totalCount", 0)
                logger.info(f"Synced 효능군중복 page {page} ({count}/{total})")
                await self._emit(source="efcy_dplct", page=page, count=count, total=total)

                if len(items) < self.PAGE_SIZE:
                    break
                page += 1
                await asyncio.sleep(0.5)

        return count

    async def _upsert_efcy_dplct(self, item: dict) -> None:
        seq = _clean(item.get("ITEM_SEQ"))
        name = _clean(item.get("ITEM_NAME"))
        dur_seq = _clean(item.get("DUR_SEQ"))
        effect_name = _clean(item.get("EFFECT_NAME"))
        if not name or not dur_seq or not effect_name:
            return

        drug = await self._find_or_create_drug_from_dur(
            seq=seq, name=name,
            entp=_clean(item.get("ENTP_NAME")),
            main_ingr=_clean(item.get("MAIN_INGR")),
            permit_date_str=_clean(item.get("ITEM_PERMIT_DATE")),
            class_name=_clean(item.get("CLASS_NAME")),
            etc_otc_name=_clean(item.get("ETC_OTC_NAME")),
        )

        existing = await self.db.scalar(
            select(DrugEffectGroup).where(
                DrugEffectGroup.drug_id == drug.id,
                DrugEffectGroup.dur_seq == dur_seq,
            )
        )
        if existing:
            return

        self.db.add(DrugEffectGroup(drug_id=drug.id, dur_seq=dur_seq, effect_name=effect_name))

    # ------------------------------------------------------------------ #
    # DUR 성분정보 — ingr_name JSONB dur_code 보강                          #
    # ------------------------------------------------------------------ #

    async def _sync_dur_ingredients(self) -> int:
        url = f"{settings.DUR_INGREDIENT_API_URL}/getDURIrdntInfoList"
        count = 0
        page = 1

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {"serviceKey": self._api_key, "pageNo": page, "numOfRows": self.PAGE_SIZE, "type": "json"}
                data = await self._fetch_page(client, url, params)
                if data is None:
                    page += 1
                    continue

                items = data.get("body", {}).get("items", [])
                if not items:
                    break

                for item in items:
                    await self._update_drug_dur_ingredient(item)
                    count += 1

                await self.db.commit()

                total = data.get("body", {}).get("totalCount", 0)
                logger.info(f"Synced DUR ingredients page {page} ({count}/{total})")
                await self._emit(source="dur_ingredients", page=page, count=count, total=total)

                if count >= total or len(items) < self.PAGE_SIZE:
                    break
                page += 1
                await asyncio.sleep(0.5)

        return count

    async def _update_drug_dur_ingredient(self, item: dict) -> None:
        item_name = _clean(item.get("ITEM_NAME") or item.get("itemName"))
        ingr_kor = _clean(item.get("INGR_KOR_NAME") or item.get("ingrKorName"))
        ingr_eng = _clean(item.get("INGR_ENG_NAME") or item.get("ingrEngName"))
        dur_seq = _clean(item.get("DUR_SEQ") or item.get("durSeq"))

        if not item_name or not ingr_kor:
            return

        drug = await self._find_drug_by_name(item_name)
        if not drug:
            return

        new_entry = {"kor": ingr_kor, "eng": ingr_eng or "", "amount": "", "dur_code": dur_seq or ""}

        if not drug.ingr_name:
            drug.ingr_name = [new_entry]
            return

        for ingr in drug.ingr_name:
            if ingr_kor in ingr.get("kor", ""):
                if ingr_eng and not ingr.get("eng"):
                    ingr["eng"] = ingr_eng
                if dur_seq and not ingr.get("dur_code"):
                    ingr["dur_code"] = dur_seq
                drug.ingr_name = list(drug.ingr_name)
                return

        drug.ingr_name = list(drug.ingr_name) + [new_entry]

    # ------------------------------------------------------------------ #
    # 낱알식별 — drug_shape, color, 각인 보강                               #
    # ------------------------------------------------------------------ #

    async def _sync_drug_identification(self) -> int:
        import xml.etree.ElementTree as ET
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

    # ------------------------------------------------------------------ #
    # 의약품 제품 허가정보                                                   #
    # ------------------------------------------------------------------ #

    async def sync_drug_approval(self) -> int:
        url = f"{settings.DRUG_APPROVAL_API_URL}/getDrugPrdtPrmsnInq07"
        count = 0
        page = 1

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {
                    "serviceKey": self._api_key,
                    "pageNo": page,
                    "numOfRows": self.PAGE_SIZE,
                    "type": "json",
                }
                data = await self._fetch_page(client, url, params)
                if data is None:
                    page += 1
                    continue

                items = data.get("body", {}).get("items", [])
                if not items:
                    break

                for item in items:
                    await self._upsert_drug_from_approval(item)
                    count += 1

                await self.db.commit()
                total = data.get("body", {}).get("totalCount", 0)
                logger.info(f"Synced drug approval page {page} ({count}/{total})")
                await self._emit(source="approval", page=page, count=count, total=total)

                if count >= total or len(items) < self.PAGE_SIZE:
                    break
                page += 1
                await asyncio.sleep(0.5)

        return count

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

    # ------------------------------------------------------------------ #
    # 공통 헬퍼                                                             #
    # ------------------------------------------------------------------ #

    async def _find_drug_by_name(self, name: str) -> Drug | None:
        drug_key = _make_drug_key(name)
        return await self.db.scalar(select(Drug).where(Drug.drug_key == drug_key))

    async def fill_simple_names(self) -> int:
        rows = await self.db.execute(select(Drug).where(Drug.simple_name.is_(None)))
        drugs = rows.scalars().all()
        count = 0
        for drug in drugs:
            drug.simple_name = _make_simple_name(drug.item_name)
            count += 1
        await self.db.commit()
        return count

    async def fill_ingr_from_main_ingr(self) -> int:
        rows = await self.db.execute(
            select(Drug).where(Drug.main_item_ingr.isnot(None), Drug.ingr_name.is_(None))
        )
        drugs = rows.scalars().all()
        count = 0
        for drug in drugs:
            parsed = _parse_main_ingr(drug.main_item_ingr)
            if parsed:
                drug.ingr_name = parsed
                count += 1
        await self.db.commit()
        return count


# ------------------------------------------------------------------ #
# 모듈 레벨 헬퍼                                                        #
# ------------------------------------------------------------------ #

def _parse_main_ingr(main_ingr: str) -> list[dict]:
    result = []
    for part in main_ingr.split('/'):
        part = part.strip()
        m = re.match(r'\[([^\]]+)\](.+)', part)
        if m:
            result.append({"kor": m.group(2).strip(), "eng": "", "amount": "", "dur_code": m.group(1)})
    return result


def _make_simple_name(item_name: str) -> str:
    name = re.sub(r'[\(\[（][^\)\]）]*[\)\]）]', '', item_name).strip()
    return name if name else item_name


def _make_drug_key(name: str) -> str:
    s = str(name)
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'밀리그램', 'mg', s)
    s = re.sub(r'밀리그람', 'mg', s)
    s = re.sub(r'마이크로그램', 'mcg', s)
    s = re.sub(r'마이크로그람', 'mcg', s)
    s = re.sub(r'그램', 'g', s)
    s = re.sub(r'그람', 'g', s)
    s = s.replace(' ', '')
    s = re.sub(r'[^\w]', '', s, flags=re.UNICODE)
    return s.lower()


def _parse_ingredients(ingr_str: str) -> list[dict]:
    amount_pattern = re.compile(r'(\d+\.?\d*)\s*(mg|mcg|g|IU|%|μg)', re.IGNORECASE)

    separators = [",", "/", "+", ";", "·"]
    parts = [ingr_str]
    for sep in separators:
        new_parts = []
        for p in parts:
            new_parts.extend(p.split(sep))
        parts = new_parts

    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        amount = ""
        m = amount_pattern.search(part)
        if m:
            amount = m.group(0).strip()
            kor_name = amount_pattern.sub('', part).strip()
        else:
            kor_name = part

        result.append({
            "kor": kor_name,
            "eng": "",
            "amount": amount,
            "dur_code": "",
        })

    return result


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None
