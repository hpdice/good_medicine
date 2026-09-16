"""DUR(병용금기·효능군중복·특정연령대금기·노인주의·기타 성분코드) 동기화.

`DURPrdlstInfoService03` 응답의 `INGR_CODE`/`MIXTURE_INGR_CODE`에서 성분코드를
캡처해 `drug_ingredients` + `dur_ingredient_*`(판정 규칙) 테이블을 채운다
(구 DUR 성분정보 API `DURIrdntInfoService`는 폐기됨)."""
import asyncio

import httpx
from sqlalchemy import select

from app.config import settings
from app.core.logging import logger
from app.models.dur_ingredient_rule import (
    DurIngredientAgeCaution,
    DurIngredientContraindication,
    DurIngredientEffectGroup,
)

from .helpers import _clean, _parse_age_criteria


class DurSyncMixin:
    CHECKPOINT_FILE = "/tmp/dur_contraindications_checkpoint.txt"

    # 특정연령대금기·노인주의는 판정 규칙(dur_ingredient_age_caution)까지 채우는
    # sync_dur_age_caution()으로 옮겼다 — 이 딕셔너리에는 성분코드 매핑만 필요한
    # 나머지(임부금기·용량주의·투여기간주의)만 남긴다. 값은 (엔드포인트, 부가값) —
    # 부가값은 _run_multi_endpoint_sync가 item_handler에 그대로 넘겨주는 자리라
    # 여기선 안 써서 None.
    DUR_EXTRA_CODE_OPS = {
        "임부금기": ("getPwnmTabooInfoList03", None),
        "용량주의": ("getCpctyAtentInfoList03", None),
        "투여기간주의": ("getMdctnPdAtentInfoList03", None),
    }

    # label -> (엔드포인트, rule_type)
    AGE_CAUTION_OPS = {
        "특정연령대금기": ("getSpcifyAgrdeTabooInfoList03", "age_taboo"),
        "노인주의": ("getOdsnAtentInfoList03", "elderly_caution"),
    }

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

    # ------------------------------------------------------------------ #
    # DUR 병용금기 — 체크포인트 재개 + 할당량초과/EOF 판별이 고유해서          #
    # 공통 루프로 통합하지 않는다                                            #
    # ------------------------------------------------------------------ #

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
    # 성분(ingredient) 단위 판정 규칙 upsert — run 내 in-memory 캐시로        #
    # 중복 스킵(캐시 자체는 base.py의 __init__에서 초기화)                    #
    # ------------------------------------------------------------------ #

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

    async def _upsert_ingr_age_caution(
        self, ingr_code: str | None, ingr_kor: str | None, rule_type: str,
        prohibit_content: str | None,
    ) -> None:
        if not ingr_code:
            return
        key = (ingr_code, rule_type)
        if key in self._seen_ingr_age:
            return
        self._seen_ingr_age.add(key)

        existing = await self.db.scalar(
            select(DurIngredientAgeCaution).where(
                DurIngredientAgeCaution.ingr_code == ingr_code,
                DurIngredientAgeCaution.rule_type == rule_type,
            )
        )
        if existing:
            return
        threshold, unit, direction = _parse_age_criteria(prohibit_content)
        self.db.add(DurIngredientAgeCaution(
            ingr_code=ingr_code, ingr_kor=ingr_kor, rule_type=rule_type,
            prohibit_content=prohibit_content,
            age_threshold=threshold, age_unit=unit, age_direction=direction,
        ))

    # ------------------------------------------------------------------ #
    # DUR 품목정보 — 효능군중복주의 (병용금기가 아닌 '주의' 등급)              #
    # ------------------------------------------------------------------ #

    async def _sync_efcy_dplct(self) -> int:
        url = f"{settings.DUR_PRODUCT_API_URL}/getEfcyDplctInfoList03"
        return await self._run_simple_paginated_sync(
            url, self._upsert_efcy_dplct, source="efcy_dplct", log_label="효능군중복",
        )

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
    # DUR 특정연령대금기·노인주의 — 판정 규칙까지 채움                        #
    # ------------------------------------------------------------------ #

    async def sync_dur_age_caution(self) -> int:
        """특정연령대금기·노인주의 → `dur_ingredient_age_caution`(판정 규칙 테이블).

        실측 확인(2026-09-12): 두 엔드포인트 다 나이 기준을 구조화한 필드가 없고
        유일한 단서인 PROHBT_CONTENT(자유 텍스트)도 "OO세 미만" 패턴은 3.6%뿐이라
        `_parse_age_criteria`가 실패하면 원문만 저장하고 판정에서 스킵한다(모델
        docstring 참고). `dur_seq` 같은 그룹핑 필드가 없어 `_sync_efcy_dplct`와
        달리 그룹 묶음 없이 성분코드 단위로 바로 upsert한다.
        """
        return await self._run_multi_endpoint_sync(
            self.AGE_CAUTION_OPS, self._handle_age_caution_item,
            error_label="DUR age caution", source_prefix="dur_age_caution",
            retry_hint="sync.py dur_age_caution",
        )

    async def _handle_age_caution_item(self, item: dict, rule_type: str) -> None:
        seq = _clean(item.get("ITEM_SEQ"))
        name = _clean(item.get("ITEM_NAME"))
        ingr_code = _clean(item.get("INGR_CODE"))
        ingr_kor = _clean(item.get("INGR_NAME"))
        if name and ingr_code:
            drug = await self._find_or_create_drug_from_dur(
                seq=seq, name=name,
                entp=_clean(item.get("ENTP_NAME")),
                main_ingr=_clean(item.get("MAIN_INGR")),
                permit_date_str=_clean(item.get("ITEM_PERMIT_DATE")),
                class_name=_clean(item.get("CLASS_NAME")),
                etc_otc_name=_clean(item.get("ETC_OTC_NAME")),
            )
            await self._upsert_drug_ingredient(drug.id, ingr_code, ingr_kor)
        await self._upsert_ingr_age_caution(
            ingr_code, ingr_kor, rule_type,
            _clean(item.get("PROHBT_CONTENT")),
        )

    # ------------------------------------------------------------------ #
    # DUR 기타 엔드포인트 — (ITEM_SEQ, INGR_CODE) 매핑만 수확                 #
    #   임부금기·용량주의·투여기간주의                                       #
    #   판정 로직에는 관여하지 않는다 — drug_ingredients 해소율 보강 전용     #
    # ------------------------------------------------------------------ #

    async def sync_dur_extra_ingredient_codes(self) -> int:
        """병용금기·효능군중복·연령대금기 외 DUR 품목 엔드포인트에서 성분코드 매핑만
        가져와 `drug_ingredients`에 채운다. 응답에 `INGR_CODE`(D코드) + `ITEM_SEQ`가
        함께 있으므로 quick_check가 쓰는 성분코드 해소율을 순수하게 높이는 용도.
        판정 규칙(dur_ingredient_*)은 건드리지 않는다.
        """
        return await self._run_multi_endpoint_sync(
            self.DUR_EXTRA_CODE_OPS, self._handle_extra_code_item,
            error_label="DUR extra codes", source_prefix="dur_extra",
            retry_hint="sync.py dur_extra_codes",
        )

    async def _handle_extra_code_item(self, item: dict, extra) -> None:
        await self._capture_ingr_code_row(item)

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
