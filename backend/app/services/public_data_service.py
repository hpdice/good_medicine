"""
공공데이터포털 의약품 API 통합 서비스.
- 의약품개요정보(e약은요): DrbEasyDrugInfoService
- 의약품안전사용서비스(DUR) 품목정보: DURPrdlstInfoService03  (응답에 성분코드 INGR_CODE 포함)
- 의약품 낱알식별 정보: MdcinGrnIdntfcInfoService01
- 의약품 제품 허가정보: DrugPrdtPrmsnInfoService07
(구 DUR 성분정보 API `DURIrdntInfoService`는 폐기됨 — 성분코드는 DUR 품목정보 응답에서 캡처)
"""
import asyncio
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import logger
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_rule import (
    DurIngredientContraindication,
    DurIngredientEffectGroup,
)
from app.models.residual_interaction import ResidualInteraction


class PublicDataService:
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
        """공공데이터 소스를 순서대로 동기화한다."""
        return {
            "drug_overview": await self._sync_drug_overview(),
            "dur_contraindications": await self._sync_dur_contraindications(),
            "efcy_dplct": await self._sync_efcy_dplct(),
            "drug_identification": await self._sync_drug_identification(),
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
    # DUR 품목정보(병용금기) sweep — 응답의 INGR_CODE로 성분 테이블을 채운다 #
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
                    # 할당량 초과/스로틀 응답은 HTTP 200 + 빈 body로 와서 정상 EOF처럼 보인다.
                    # totalCount 대비 아직 한참 남았는데 비어 있으면 EOF가 아니라 중단으로 본다 —
                    # 체크포인트를 유지한 채 raise 해서 할당량 리셋 후 이어받게 한다.
                    total = data.get("body", {}).get("totalCount", 0)
                    err = (
                        data.get("OpenAPI_ServiceResponse", {})
                        .get("cmmMsgHeader", {})
                        .get("errMsg")
                    )
                    expected_last_page = -(-total // self.PAGE_SIZE) if total else 0
                    if err or (expected_last_page and page < expected_last_page):
                        self._save_checkpoint(page)
                        raise RuntimeError(
                            f"DUR 병용금기 페이지 {page}/{expected_last_page} 빈 응답 (err={err}). "
                            f"체크포인트 유지 — 할당량 리셋 후 재실행하면 이어서 진행."
                        )
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

        # 성분(ingredient) 단위 캡처 — 같은 응답 행에 INGR_CODE가 들어있다.
        # drug_a/drug_b는 성분코드를 붙일 Drug 레코드를 확보하려고 조회·생성한 것.
        code_a = _clean(item.get("INGR_CODE"))
        code_b = _clean(item.get("MIXTURE_INGR_CODE"))
        ingr_kor_a = _clean(item.get("INGR_KOR_NAME") or item.get("INGR_NAME"))
        ingr_kor_b = _clean(item.get("MIXTURE_INGR_KOR_NAME") or item.get("MIXTURE_INGR_NAME"))
        await self._upsert_drug_ingredient(drug_a.id, code_a, ingr_kor_a)
        await self._upsert_drug_ingredient(drug_b.id, code_b, ingr_kor_b)
        await self._upsert_ingr_contraindication(
            code_a, code_b, ingr_kor_a, ingr_kor_b,
            prohibit_content=mechanism, remark=_clean(item.get("REMARK")),
        )
        # 품목쌍(구 drug_interactions)은 폐기됨 — 이 sweep은 이제 성분 테이블만 채운다.

    # ------------------------------------------------------------------ #
    # 성분(ingredient) 단위 upsert 헬퍼 — run 내 in-memory 캐시로 중복 스킵   #
    # ------------------------------------------------------------------ #

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

    async def _upsert_ingr_contraindication(
        self, code_a: str | None, code_b: str | None,
        kor_a: str | None, kor_b: str | None,
        prohibit_content: str | None, remark: str | None,
    ) -> None:
        if not code_a or not code_b or code_a == code_b:
            return
        # 정규 순서 a<b로 저장 (조회는 양방향 IN 교집합이라 한 방향이면 충분)
        if code_a > code_b:
            code_a, code_b = code_b, code_a
            kor_a, kor_b = kor_b, kor_a
        if (code_a, code_b) in self._seen_ingr_contra:
            return
        self._seen_ingr_contra.add((code_a, code_b))

        existing = await self.db.scalar(
            select(DurIngredientContraindication).where(
                DurIngredientContraindication.ingr_code_a == code_a,
                DurIngredientContraindication.ingr_code_b == code_b,
            )
        )
        if existing:
            return
        self.db.add(DurIngredientContraindication(
            ingr_code_a=code_a, ingr_code_b=code_b,
            ingr_kor_a=kor_a, ingr_kor_b=kor_b,
            prohibit_content=prohibit_content, remark=remark,
        ))

    async def _upsert_ingr_effect_group(
        self, ingr_code: str | None, dur_seq: str | None, effect_name: str | None,
    ) -> None:
        if not ingr_code or not dur_seq or not effect_name:
            return
        key = (ingr_code, dur_seq)
        if key in self._seen_ingr_effect:
            return
        self._seen_ingr_effect.add(key)

        existing = await self.db.scalar(
            select(DurIngredientEffectGroup).where(
                DurIngredientEffectGroup.ingr_code == ingr_code,
                DurIngredientEffectGroup.dur_seq == dur_seq,
            )
        )
        if existing:
            return
        self.db.add(DurIngredientEffectGroup(
            ingr_code=ingr_code, dur_seq=dur_seq, effect_name=effect_name,
        ))

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

        # 성분 단위 캡처 — 같은 행에 INGR_CODE 포함
        ingr_code = _clean(item.get("INGR_CODE"))
        ingr_kor = _clean(item.get("INGR_NAME") or item.get("INGR_KOR_NAME"))
        await self._upsert_drug_ingredient(drug.id, ingr_code, ingr_kor)
        await self._upsert_ingr_effect_group(ingr_code, dur_seq, effect_name)
        # 품목 단위 drug_effect_groups는 폐기됨 — 이 sweep도 성분 테이블만 채운다.

    # ------------------------------------------------------------------ #
    # DUR 기타 엔드포인트 — (ITEM_SEQ, INGR_CODE) 매핑만 수확                 #
    #   특정연령대금기·노인주의·임부금기·용량주의·투여기간주의               #
    #   판정 로직에는 관여하지 않는다 — drug_ingredients 해소율 보강 전용     #
    # ------------------------------------------------------------------ #

    DUR_EXTRA_CODE_OPS = {
        "특정연령대금기": "getSpcifyAgrdeTabooInfoList03",
        "노인주의": "getOdsnAtentInfoList03",
        "임부금기": "getPwnmTabooInfoList03",
        "용량주의": "getCpctyAtentInfoList03",
        "투여기간주의": "getMdctnPdAtentInfoList03",
    }

    async def sync_dur_extra_ingredient_codes(self) -> int:
        """병용금기·효능군중복 외 DUR 품목 엔드포인트에서 성분코드 매핑만 가져와
        `drug_ingredients`에 채운다. 응답에 `INGR_CODE`(D코드) + `ITEM_SEQ`가 함께
        있으므로 quick_check가 쓰는 성분코드 해소율을 순수하게 높이는 용도.
        판정 규칙(dur_ingredient_*)은 건드리지 않는다.
        """
        processed = 0
        for label, op in self.DUR_EXTRA_CODE_OPS.items():
            url = f"{settings.DUR_PRODUCT_API_URL}/{op}"
            page = 1
            ep_count = 0  # 이 엔드포인트에서 처리한 행 수 (진행바 total과 짝을 맞춤)
            consecutive_failures = 0
            async with httpx.AsyncClient(timeout=30) as client:
                while True:
                    params = {
                        "serviceKey": self._api_key, "pageNo": page,
                        "numOfRows": self.PAGE_SIZE, "type": "json",
                    }
                    data = await self._fetch_page(client, url, params)
                    if data is None:
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            raise RuntimeError(
                                f"DUR extra codes [{label}] page {page} 연속 실패 — 할당량 초과 추정. "
                                f"할당량 리셋 후 `sync.py dur_extra_codes` 재실행."
                            )
                        page += 1
                        continue
                    consecutive_failures = 0

                    items = data.get("body", {}).get("items", [])
                    if not items:
                        break

                    for item in items:
                        await self._capture_ingr_code_row(item)
                        ep_count += 1
                        processed += 1

                    await self.db.commit()
                    total = data.get("body", {}).get("totalCount", 0)
                    logger.info(f"DUR extra codes [{label}] page {page} ({ep_count}/{total})")
                    await self._emit(
                        source=f"dur_extra:{label}", page=page, count=ep_count, total=total
                    )

                    if len(items) < self.PAGE_SIZE:
                        break
                    page += 1
                    await asyncio.sleep(0.5)

        return processed

    async def _capture_ingr_code_row(self, item: dict) -> None:
        seq = _clean(item.get("ITEM_SEQ"))
        name = _clean(item.get("ITEM_NAME"))
        code = _clean(item.get("INGR_CODE"))
        if not name or not code:
            return
        drug = await self._find_or_create_drug_from_dur(
            seq=seq, name=name,
            entp=_clean(item.get("ENTP_NAME")),
            main_ingr=_clean(item.get("MAIN_INGR")),
            permit_date_str=_clean(item.get("ITEM_PERMIT_DATE")),
            class_name=_clean(item.get("CLASS_NAME")),
            etc_otc_name=_clean(item.get("ETC_OTC_NAME")),
        )
        await self._upsert_drug_ingredient(
            drug.id, code, _clean(item.get("INGR_NAME") or item.get("INGR_KOR_NAME"))
        )

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

    async def build_drug_ingredients_from_jsonb(self) -> int:
        """API 미사용 로컬 폴백 — DUR sweep이 채운 `drug_ingredients`(source='dur')에서
        `{정규화 성분명: ingr_code}` 사전을 만들고, `drug_ingredients` 행이 없는 약품의
        성분명 후보를 이름으로 매칭해 보강한다 (source='jsonb_fallback').

        성분명 후보는 세 군데서 모은다:
          1. `ingr_name` JSONB의 kor
          2. `main_item_ingr`의 `[Mxxxx]성분명` 파싱 결과
          3. `item_name` 괄호 안 텍스트 — 외용제(겔·플라스타 등)는 식약처가 DUR 성분코드를
             안 붙여 병용금기 원본에 INGR_CODE가 NULL로 오는 경우가 많은데, 제품명
             '뉴펜겔(케토프로펜)'처럼 괄호에 성분명이 노출된다.
        완전 매칭 → 접두(염 형태) 매칭 순.
        """
        rows = await self.db.execute(
            select(DrugIngredient.ingr_kor, DrugIngredient.ingr_code)
            .where(DrugIngredient.ingr_code.isnot(None), DrugIngredient.ingr_kor.isnot(None))
        )
        name_to_code: dict[str, str] = {}
        for ingr_kor, ingr_code in rows.all():
            key = _make_drug_key(ingr_kor)
            if key and key not in name_to_code:
                name_to_code[key] = ingr_code
        if not name_to_code:
            return 0
        code_keys = sorted(name_to_code)

        def _resolve(cand: str) -> str | None:
            key = _make_drug_key(cand)
            if len(key) < 3:
                return None
            code = name_to_code.get(key)
            if code:
                return code
            for ck in code_keys:
                if ck.startswith(key) or key.startswith(ck):
                    return name_to_code[ck]
            return None

        covered = set(
            (await self.db.execute(select(DrugIngredient.drug_id).distinct())).scalars().all()
        )
        drug_rows = await self.db.execute(
            select(Drug.id, Drug.item_name, Drug.ingr_name, Drug.main_item_ingr)
        )

        count = 0
        for drug_id, item_name, ingr_name, main_item_ingr in drug_rows.all():
            if drug_id in covered:
                continue

            candidates: list[str] = []
            for entry in ingr_name or []:
                kor = (entry or {}).get("kor")
                if kor:
                    candidates.append(kor)
            for entry in _parse_main_ingr(main_item_ingr or ""):
                if entry.get("kor"):
                    candidates.append(entry["kor"])
            for paren in re.findall(r'[\(\[（]([^\)\]）]+)[\)\]）]', item_name or ""):
                for part in re.split(r'[,/·]', paren):
                    part = part.strip()
                    if part:
                        candidates.append(part)

            seen_codes: set[str] = set()
            for cand in candidates:
                code = _resolve(cand)
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                self.db.add(DrugIngredient(
                    drug_id=drug_id, ingr_code=code, ingr_kor=cand, source="jsonb_fallback",
                ))
                count += 1
            if count and count % 2000 == 0:
                await self.db.commit()
        await self.db.commit()
        return count

    SEED_RESIDUAL_PATH = Path(__file__).resolve().parents[2] / "seed" / "residual_interactions.json"

    async def build_residual_from_seed(self) -> int:
        """`seed/residual_interactions.json`(item_seq 쌍 기준)에서 `residual_interactions`를
        채운다. 마이그레이션 0006이 구 품목 테이블에서 뽑아 넣지만, DB를 완전 초기화
        (`down -v`)하면 그 테이블이 빈 채로 드롭돼 잔여 폴백이 사라진다 — 그 경우
        `sync.py build_residual`로 이 시드에서 복원한다. UUID가 초기화마다 바뀌므로
        `item_seq`로 저장하고 로드 시 `drug_id`로 해소한다. 재실행 안전(이미 있으면 skip).
        """
        entries = json.loads(self.SEED_RESIDUAL_PATH.read_text(encoding="utf-8"))

        # item_seq → drug_id, 기존 쌍 집합을 각각 쿼리 1번으로 미리 로드 (N+1 방지)
        seqs = {e["seq1"] for e in entries} | {e["seq2"] for e in entries}
        seq_to_id = dict(
            (await self.db.execute(
                select(Drug.item_seq, Drug.id).where(Drug.item_seq.in_(seqs))
            )).all()
        )
        existing = {
            (frozenset((r.drug1_id, r.drug2_id)), r.interaction_type)
            for r in (await self.db.execute(
                select(
                    ResidualInteraction.drug1_id,
                    ResidualInteraction.drug2_id,
                    ResidualInteraction.interaction_type,
                )
            )).all()
        }

        count = skipped = missing = 0
        for e in entries:
            id1, id2 = seq_to_id.get(e["seq1"]), seq_to_id.get(e["seq2"])
            if not id1 or not id2:
                missing += 1
                continue
            if (frozenset((id1, id2)), e["type"]) in existing:
                skipped += 1
                continue
            self.db.add(ResidualInteraction(
                drug1_id=id1, drug2_id=id2,
                interaction_type=e["type"], mechanism=e.get("mechanism"),
            ))
            count += 1
        await self.db.commit()
        logger.info(
            f"residual 시드 로드: {count}건 추가 / {skipped}건 기존 / {missing}건 약품 미발견"
        )
        return count

    _RISK_TAG_SYSTEM = (
        "너는 의약품 병용금기 설명 문장에서 '환자에게 나타날 수 있는 위험/증상'만 뽑아내는 추출기다. "
        "문장에 없는 내용은 지어내지 마라. 효소 저해 같은 '기전'이 아니라 결과(출혈, 신독성, QT 연장 등)를 뽑아라."
    )

    async def extract_risk_tags(self, batch_commit: int = 20) -> int:
        """`dur_ingredient_contraindications.prohibit_content`(distinct ~127개)를 로컬 LLM으로
        1회 태그화해 `risk_tags` JSONB에 저장한다. `risk_tags`가 NULL인 행만 처리(재실행 안전).
        Ollama가 없으면 조용히 스킵(판정엔 영향 없음).
        """
        from app.services.ollama_client import OllamaClient, OllamaUnavailableError

        contents = (await self.db.execute(text("""
            SELECT DISTINCT prohibit_content FROM dur_ingredient_contraindications
            WHERE prohibit_content IS NOT NULL AND risk_tags IS NULL
        """))).scalars().all()
        if not contents:
            return 0

        ollama = OllamaClient()
        done = 0
        for i, pc in enumerate(contents, 1):
            prompt = (
                f'다음 문장에서 위험/증상을 한국어 명사구로 최대 4개 뽑아 JSON 배열로만 답해라. '
                f'없으면 []. 문장: "{pc}"'
            )
            try:
                raw = await ollama.generate(prompt, system=self._RISK_TAG_SYSTEM)
            except OllamaUnavailableError:
                logger.warning("Ollama 미가용 — risk_tags 추출 중단 (%d/%d 처리됨)", done, len(contents))
                break
            tags = _parse_tag_array(raw)
            await self.db.execute(
                text("UPDATE dur_ingredient_contraindications SET risk_tags = :t "
                     "WHERE prohibit_content = :pc"),
                {"t": json.dumps(tags, ensure_ascii=False), "pc": pc},
            )
            done += 1
            if i % batch_commit == 0:
                await self.db.commit()
        await self.db.commit()
        logger.info(f"risk_tags 추출 완료: {done}/{len(contents)} distinct 문장")
        return done


# ------------------------------------------------------------------ #
# 모듈 레벨 헬퍼                                                        #
# ------------------------------------------------------------------ #

def _parse_tag_array(raw: str) -> list[str]:
    """LLM 응답에서 첫 `[` ~ 마지막 `]` 사이를 JSON 배열로 파싱. 실패 시 []."""
    s, e = raw.find("["), raw.rfind("]")
    if s == -1 or e == -1 or e < s:
        return []
    try:
        arr = json.loads(raw[s:e + 1])
    except (ValueError, TypeError):
        return []
    out, seen = [], set()
    for x in arr:
        x = str(x).strip()
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:4]

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
