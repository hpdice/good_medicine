"""DUR 성분정보(`DURIrdntInfoService03`) → 성분코드 조회표 + 판정 규칙.

품목정보(`DURPrdlstInfoService03`)는 성분 규칙을 품목 쌍으로 풀어 내려주는데, 풀린 범위가 규칙의
일부뿐이다(실측: 할로페리돌의 병용금기 상대 성분 25개 중 품목 응답엔 3개, 로수바스타틴은 행 0건).
성분정보는 규칙 자체를 성분 단위로 준다. 여기서
- `dur_ingredient_master`: D코드 ↔ 한글·영문 성분명 — 판정 미사용, 심평원 경로 해소(source='hira_eng')의 기준
- 판정 규칙(병용금기·효능군중복·특정연령대금기·노인주의)에 성분정보에만 있는 규칙을 `source='ingredient'`로 더한다.
  기존 품목정보 유래 행('product')은 지우지 않는다.
임부금기는 제형·적응증 범위 때문에 품목 단위 규칙(`dur_item_pregnancy_taboo`)을 그대로 쓴다."""
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.core.logging import logger
from app.models.dur_ingredient_master import DurIngredientMaster
from app.models.dur_ingredient_rule import (
    DurIngredientAgeCaution,
    DurIngredientContraindication,
    DurIngredientEffectGroup,
)

from .base import _SyncBase
from .helpers import (
    age_rules_from_ingredient,
    contraindication_rules_from_ingredient,
    effect_groups_from_ingredient,
    ingredient_master_from_rows,
    norm_ingr_eng,
)


class DurIngredientSyncMixin(_SyncBase):
    # 오퍼레이션 7개 모두 numOfRows=500까지 되고 1000이면 빈 응답이다(실측).
    INGR_PAGE_SIZE: int = 500

    # label -> (엔드포인트, handler에 넘길 라벨)
    INGR_OPS = {
        label: (op, label) for label, op in (
            ("병용금기", "getUsjntTabooInfoList02"),
            ("효능군중복", "getEfcyDplctInfoList02"),
            ("임부금기", "getPwnmTabooInfoList02"),
            ("특정연령대금기", "getSpcifyAgrdeTabooInfoList02"),
            ("노인주의", "getOdsnAtentInfoList02"),
            ("용량주의", "getCpctyAtentInfoList02"),
            ("투여기간주의", "getMdctnPdAtentInfoList02"),
        )
    }

    async def sync_dur_ingredient(self) -> int:
        """7개 오퍼레이션을 모두 받아 메모리에 모은 뒤 조회표와 판정 규칙을 한 번에 쓴다(전체 4,852행 안팎).
        같은 성분이 수백 행에 반복되므로 행마다 DB에 쓰지 않는다."""
        self._ingr_rows: dict[str, list[dict]] = {label: [] for label in self.INGR_OPS}
        rows = await self._run_multi_endpoint_sync(
            self.INGR_OPS, self._collect_ingredient_row, source="dur_ingredient",
            size=self.INGR_PAGE_SIZE, base_url=settings.DUR_INGREDIENT_API_URL,
        )
        await self._write_ingredient_master()
        await self._write_ingredient_rules()
        await self.db.commit()
        return rows

    async def _collect_ingredient_row(self, item: dict, label: str) -> None:
        self._ingr_rows[label].append(item.get("item", item))  # 응답 행은 {"item": {...}}로 한 겹 싸여 온다

    # ------------------------------------------------------------------ #
    # 조회표 — 성분코드 ↔ 이름                                              #
    # ------------------------------------------------------------------ #

    async def _write_ingredient_master(self) -> None:
        names = ingredient_master_from_rows(self._ingr_rows)
        for (code, kor, eng), mix_type in names.items():
            stmt = pg_insert(DurIngredientMaster).values(
                ingr_code=code, ingr_kor=kor, ingr_eng=eng, ingr_eng_norm=norm_ingr_eng(eng), mix_type=mix_type,
            )
            await self.db.execute(stmt.on_conflict_do_update(
                constraint="uq_dur_ingr_master_code_names",
                set_={"mix_type": stmt.excluded.mix_type, "updated_at": func.now()},
                where=DurIngredientMaster.mix_type.is_distinct_from(stmt.excluded.mix_type),
            ))
        logger.info("DUR 성분정보 조회표: 이름 조합 %d개", len(names))

    # ------------------------------------------------------------------ #
    # 판정 규칙 — 성분정보에만 있는 규칙을 더한다                              #
    # ------------------------------------------------------------------ #

    async def _write_ingredient_rules(self) -> None:
        added = {"병용금기": 0, "효능군중복": 0, "특정연령대금기": 0, "노인주의": 0}

        for (a, b), rule in contraindication_rules_from_ingredient(self._ingr_rows["병용금기"]).items():
            # 이미 있는 쌍(품목정보 유래)은 문구·risk_tags를 그대로 둔다.
            result = await self.db.execute(pg_insert(DurIngredientContraindication).values(
                ingr_code_a=a, ingr_code_b=b, source="ingredient", **rule,
            ).on_conflict_do_nothing(constraint="uq_dur_ingr_contra_pair"))
            added["병용금기"] += result.rowcount  # type: ignore[attr-defined]

        for (code, seq), group in effect_groups_from_ingredient(self._ingr_rows["효능군중복"]).items():
            stmt = pg_insert(DurIngredientEffectGroup).values(
                ingr_code=code, dur_seq=seq, source="ingredient", **group,
            )
            # 이미 있는 행은 계열명만 채운다(품목정보 동기화가 계열을 저장하기 전에 들어간 행).
            result = await self.db.execute(stmt.on_conflict_do_update(
                constraint="uq_dur_ingr_effect_ingr_dur_seq",
                set_={"sers_name": stmt.excluded.sers_name},
                where=DurIngredientEffectGroup.sers_name.is_(None),
            ).returning(DurIngredientEffectGroup.source))
            added["효능군중복"] += sum(1 for (src,) in result if src == "ingredient")

        for label, rule_type, with_age_base in (("특정연령대금기", "age_taboo", True), ("노인주의", "elderly_caution", False)):
            for code, rule in age_rules_from_ingredient(self._ingr_rows[label], with_age_base=with_age_base).items():
                stmt = pg_insert(DurIngredientAgeCaution).values(
                    ingr_code=code, rule_type=rule_type, source="ingredient", **rule,
                )
                # 이미 있는 규칙은 나이 기준만 AGE_BASE(구조화 값)로 채운다. 문구는 그대로 둔다.
                result = await self.db.execute(stmt.on_conflict_do_update(
                    constraint="uq_dur_ingr_age_caution_code_type",
                    set_={"age_threshold": stmt.excluded.age_threshold, "age_unit": stmt.excluded.age_unit,
                          "age_direction": stmt.excluded.age_direction},
                    where=stmt.excluded.age_threshold.isnot(None),
                ).returning(DurIngredientAgeCaution.source))
                added[label] += sum(1 for (src,) in result if src == "ingredient")

        logger.info("DUR 성분정보 판정 규칙 추가(신규 또는 갱신): %s", added)
