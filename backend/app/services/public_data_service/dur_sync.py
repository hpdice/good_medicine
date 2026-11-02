"""DUR(병용금기·효능군중복·특정연령대금기·노인주의·임부금기) 동기화.

`DURPrdlstInfoService03` 응답의 `INGR_CODE`/`MIXTURE_INGR_CODE`에서 성분코드를
캡처해 `drug_ingredients` + `dur_ingredient_*`(판정 규칙) 테이블을 채운다.
품목정보는 성분 규칙의 일부만 풀어 주므로, 규칙은 DUR 성분정보(`dur_ingredient_sync.py`)로 보강한다."""
import os

from sqlalchemy import select

from app.config import settings
from app.core.logging import logger
from app.models.dur_ingredient_rule import (
    DurIngredientAgeCaution,
    DurIngredientContraindication,
    DurIngredientEffectGroup,
    DurItemPregnancyTaboo,
)

from .base import _SyncBase
from .helpers import _clean, _clean_text, _parse_age_criteria


class DurSyncMixin(_SyncBase):
    # DUR 계열(DURPrdlstInfoService03) 엔드포인트는 전부 numOfRows=500까지 된다
    # (그 이상은 빈 응답) — 기본 PAGE_SIZE(100, 다른 API 서비스 공용)보다
    # 5배 커서 페이지 수·sleep 총량이 그만큼 준다. 체크포인트는 페이지 "번호"만
    # 저장하므로, 이 값을 바꾸면 진행 중이던 이전 체크포인트와 어긋난다 — 바꿀 땐
    # 먼저 체크포인트 파일이 없는(=완료됐거나 시작 전) 상태인지 확인할 것.
    DUR_PAGE_SIZE: int = 500

    # label -> (엔드포인트, rule_type)
    AGE_CAUTION_OPS = {
        "특정연령대금기": ("getSpcifyAgrdeTabooInfoList03", "age_taboo"),
        "노인주의": ("getOdsnAtentInfoList03", "elderly_caution"),
    }

    # 용량주의(6,611행, 본문 있는 건 2,601행)·투여기간주의(646행, 본문 0건)는 적재하지 않는다 —
    # 판정에 쓸 구조화된 용량·기간 기준이 원본에 없어 규칙으로 못 만든다.

    @property
    def CHECKPOINT_FILE(self) -> str:  # noqa: N802 — 기존 속성명 유지(스크립트·문서 호환)
        # 체크포인트는 SYNC_STATE_DIR(compose 의 sync_state 볼륨)에 둔다. 컨테이너 /tmp 에 두면
        # 컨테이너가 재생성될 때 사라져, 7시간짜리 sweep 을 처음부터 다시 받아야 한다.
        return os.path.join(settings.SYNC_STATE_DIR, "dur_contraindications_checkpoint.txt")

    def _load_checkpoint(self) -> int:
        try:
            with open(self.CHECKPOINT_FILE) as f:
                return int(f.read().strip())
        except Exception:
            return 1

    def _save_checkpoint(self, next_page: int) -> None:
        """다음에 받을 페이지 번호를 남긴다. 저장 실패를 삼키면 "체크포인트 있음"이라 믿고 돌다가
        끊겼을 때 처음부터 다시 받게 되므로, 적재는 계속하되 크게 남긴다."""
        try:
            os.makedirs(os.path.dirname(self.CHECKPOINT_FILE), exist_ok=True)
            with open(self.CHECKPOINT_FILE, "w") as f:
                f.write(str(next_page))
        except OSError:
            logger.error("체크포인트 저장 실패 (%s) — 중단 시 이어받기 불가", self.CHECKPOINT_FILE,
                         exc_info=True)

    def _clear_checkpoint(self) -> None:
        try:
            os.remove(self.CHECKPOINT_FILE)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------ #
    # 병용금기 — 797K행이라 체크포인트로 중단 지점부터 이어받는다                #
    # ------------------------------------------------------------------ #

    async def _sync_dur_contraindications(self) -> int:
        if self.change_since:
            # 변경분 수집은 페이지 번호 체계가 전체 sweep과 달라 체크포인트를 쓰지도 지우지도 않는다.
            return await self._sync_endpoint(
                f"{settings.DUR_PRODUCT_API_URL}/getUsjntTabooInfoList03", self._upsert_dur_contraindication,
                source="dur_contraindications", label=f"DUR 병용금기 ({self.change_since} 이후 변경분)",
                size=self.DUR_PAGE_SIZE, delay=1.5,
            )
        start = self._load_checkpoint()
        if start > 1:
            logger.info(f"DUR 병용금기 체크포인트에서 재시작: 페이지 {start}")

        count = await self._sync_endpoint(
            f"{settings.DUR_PRODUCT_API_URL}/getUsjntTabooInfoList03", self._upsert_dur_contraindication,
            source="dur_contraindications", label="DUR 병용금기",
            size=self.DUR_PAGE_SIZE, start=start, delay=1.5, on_page_done=self._save_checkpoint,
        )

        self._clear_checkpoint()
        if self._updated_ingr_contra:
            logger.warning("금기 사유 문장이 바뀐 성분쌍 규칙 %d건 갱신 (risk_tags 초기화 → extract_risk_tags 필요)",
                           self._updated_ingr_contra)
        return count

    async def _upsert_dur_contraindication(self, item: dict) -> None:
        """품목쌍 한 행을 성분쌍 규칙으로 바꿔 적재한다. 같은 행에 INGR_CODE가 모두 들어 있다."""
        if not (_clean(item.get("ITEM_NAME")) and _clean(item.get("MIXTURE_ITEM_NAME"))):
            return  # 짝이 빠진 행으로 한쪽 약만 만들지 않는다
        drug_a = await self._find_or_create_drug_from_dur(item)
        drug_b = await self._find_or_create_drug_from_dur(item, "MIXTURE_")
        if drug_a is None or drug_b is None:  # 위에서 걸렀지만 타입상 필요
            return

        code_a = _clean(item.get("INGR_CODE"))
        code_b = _clean(item.get("MIXTURE_INGR_CODE"))
        kor_a = _clean(item.get("INGR_KOR_NAME") or item.get("INGR_NAME"))
        kor_b = _clean(item.get("MIXTURE_INGR_KOR_NAME") or item.get("MIXTURE_INGR_NAME"))
        await self._upsert_drug_ingredient(drug_a.id, code_a, kor_a)
        await self._upsert_drug_ingredient(drug_b.id, code_b, kor_b)
        await self._upsert_ingr_contraindication(
            code_a, code_b, kor_a, kor_b,
            prohibit_content=_clean(item.get("PROHBT_CONTENT")), remark=_clean(item.get("REMARK")),
        )

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
        if not self._first_time("contraindication", code_a, code_b):
            return

        existing = await self.db.scalar(
            select(DurIngredientContraindication).where(
                DurIngredientContraindication.ingr_code_a == code_a,
                DurIngredientContraindication.ingr_code_b == code_b,
            )
        )
        if existing is None:
            self.db.add(DurIngredientContraindication(
                ingr_code_a=code_a, ingr_code_b=code_b, ingr_kor_a=kor_a, ingr_kor_b=kor_b,
                prohibit_content=prohibit_content, remark=remark,
            ))
        elif prohibit_content and existing.prohibit_content != prohibit_content:
            # 원천(식약처)이 금기 사유 문장을 고쳐 내려주면 반영한다. 문장이 바뀌면 그 문장에서 뽑아 둔
            # risk_tags 도 낡은 값이 되므로 비워 둔다(sync.py extract_risk_tags 가 NULL 만 다시 뽑음).
            existing.prohibit_content = prohibit_content
            existing.remark = remark
            existing.risk_tags = None
            self._updated_ingr_contra += 1

    # ------------------------------------------------------------------ #
    # 효능군중복주의 — '주의' 등급                                           #
    # ------------------------------------------------------------------ #

    async def _sync_efcy_dplct(self) -> int:
        return await self._sync_endpoint(
            f"{settings.DUR_PRODUCT_API_URL}/getEfcyDplctInfoList03", self._upsert_efcy_dplct,
            source="efcy_dplct", label="효능군중복", size=self.DUR_PAGE_SIZE,
        )

    async def _upsert_efcy_dplct(self, item: dict) -> None:
        dur_seq = _clean(item.get("DUR_SEQ"))
        effect_name = _clean(item.get("EFFECT_NAME"))
        if not dur_seq or not effect_name:
            return
        drug = await self._find_or_create_drug_from_dur(item)
        if drug is None:
            return

        ingr_code = _clean(item.get("INGR_CODE"))
        await self._upsert_drug_ingredient(drug.id, ingr_code, _clean(item.get("INGR_NAME") or item.get("INGR_KOR_NAME")))
        if ingr_code:
            # 효능군중복은 효능군 + 계열 단위로 판정한다 — 원천이 계열명을 고쳐 내려주면 반영(overwrite).
            await self._insert_once(
                DurIngredientEffectGroup, ("ingr_code", "dur_seq"),
                {"ingr_code": ingr_code, "dur_seq": dur_seq, "effect_name": effect_name,
                 "sers_name": _clean(item.get("SERS_NAME"))},
                overwrite=True,
            )

    # ------------------------------------------------------------------ #
    # 특정연령대금기·노인주의                                                #
    # ------------------------------------------------------------------ #

    async def sync_dur_age_caution(self) -> int:
        """특정연령대금기·노인주의 → `dur_ingredient_age_caution`(판정 규칙 테이블).

        두 엔드포인트 다 나이 기준을 구조화한 필드가 없고
        유일한 단서인 PROHBT_CONTENT(자유 텍스트)도 "OO세 미만" 패턴은 3.6%뿐이라
        `_parse_age_criteria`가 실패하면 원문만 저장하고 판정에서 스킵한다(모델
        docstring 참고). `dur_seq` 같은 그룹핑 필드가 없어 효능군중복과 달리
        그룹 묶음 없이 성분코드 단위로 바로 upsert한다.
        """
        return await self._run_multi_endpoint_sync(
            self.AGE_CAUTION_OPS, self._handle_age_caution_item,
            source="dur_age_caution", size=self.DUR_PAGE_SIZE,
        )

    async def _handle_age_caution_item(self, item: dict, rule_type: str) -> None:
        ingr_code = _clean(item.get("INGR_CODE"))
        if not ingr_code:
            return
        ingr_kor = _clean(item.get("INGR_NAME"))
        drug = await self._find_or_create_drug_from_dur(item)
        if drug is not None:
            await self._upsert_drug_ingredient(drug.id, ingr_code, ingr_kor)

        prohibit_content = _clean(item.get("PROHBT_CONTENT"))
        threshold, unit, direction = _parse_age_criteria(prohibit_content)
        await self._insert_once(
            DurIngredientAgeCaution, ("ingr_code", "rule_type"),
            {
                "ingr_code": ingr_code, "ingr_kor": ingr_kor, "rule_type": rule_type,
                "prohibit_content": prohibit_content,
                "age_threshold": threshold, "age_unit": unit, "age_direction": direction,
            },
        )

    # ------------------------------------------------------------------ #
    # 임부금기 — 성분이 아니라 품목 단위 판정 규칙                              #
    # ------------------------------------------------------------------ #

    async def sync_dur_pregnancy_taboo(self) -> int:
        """임부금기 → `dur_item_pregnancy_taboo`(판정 규칙) + 성분코드 매핑(해소율 보강).

        성분이 아니라 품목 단위로 적재하는 이유는 모델 docstring 참고(비고에 제형·적응증
        범위가 붙어 있어 성분으로 합치면 오탐)."""
        return await self._sync_endpoint(
            f"{settings.DUR_PRODUCT_API_URL}/getPwnmTabooInfoList03", self._handle_pregnancy_taboo_item,
            source="dur_pregnancy", label="DUR 임부금기", size=self.DUR_PAGE_SIZE,
        )

    async def _handle_pregnancy_taboo_item(self, item: dict) -> None:
        ingr_code = _clean(item.get("INGR_CODE"))
        if not ingr_code:
            return
        ingr_kor = _clean(item.get("INGR_NAME") or item.get("INGR_KOR_NAME"))
        drug = await self._find_or_create_drug_from_dur(item)
        if drug is not None:
            await self._upsert_drug_ingredient(drug.id, ingr_code, ingr_kor)

        item_seq = _clean(item.get("ITEM_SEQ"))
        if item_seq:
            # 원천이 사유·비고를 고쳐 내려주면 반영한다(overwrite).
            await self._insert_once(
                DurItemPregnancyTaboo, ("item_seq", "ingr_code"),
                {
                    "item_seq": item_seq, "ingr_code": ingr_code, "ingr_kor": ingr_kor,
                    "prohibit_content": _clean_text(item.get("PROHBT_CONTENT")),
                    "remark": _clean_text(item.get("REMARK")),
                },
                overwrite=True,
            )
