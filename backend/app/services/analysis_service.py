import itertools
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.drug import Drug
from app.schemas.analysis import (
    AgeCaution,
    AllergyConflict,
    PregnancyCaution,
    QuickCheckFinding,
    QuickCheckResponse,
)
from app.services.drug_service import DrugService
from app.services.user_service import UserService

# 노인주의 엔드포인트(getOdsnAtentInfoList03) 자체가 "노인 대상" 성분만 다루므로
# 개별 규칙에 나이 기준이 없다 — 통상적인 한국 노인 기준(만 65세)을 고정값으로 쓴다.
ELDERLY_AGE_THRESHOLD = 65


def _display_name(drug: Drug) -> str:
    return drug.simple_name or drug.item_name


def _age_taboo_applies(age_years: int, threshold: int, unit: str, direction: str) -> bool:
    """`age_threshold`/`age_unit`/`age_direction`(모두 파싱 성공했을 때만 채워짐)로
    나이 조건을 계산한다. 생년월일이 아니라 출생연도만 수집하므로 "개월" 단위
    기준은 근사치(threshold/12)로 연 단위 비교한다."""
    threshold_years = threshold / 12 if unit == "개월" else threshold
    if direction == "미만":
        return age_years < threshold_years
    if direction == "이상":
        return age_years >= threshold_years
    if direction == "이하":
        return age_years <= threshold_years
    if direction == "초과":
        return age_years > threshold_years
    return False


def _risk_level(
    findings: list[QuickCheckFinding],
    allergy_conflicts: list[AllergyConflict],
    age_cautions: list[AgeCaution],
    pregnancy_cautions: list[PregnancyCaution] = (),
) -> str:
    types = {f.interaction_type for f in findings}
    has_age_taboo = any(a.rule_type == "age_taboo" for a in age_cautions)
    has_elderly_caution = any(a.rule_type == "elderly_caution" for a in age_cautions)
    if "contraindicated" in types or allergy_conflicts or has_age_taboo or pregnancy_cautions:
        return "critical"
    if "duplicate_effect_group" in types or has_elderly_caution:
        return "caution"
    return "safe"


class AnalysisService:
    """복약함 약품 목록의 병용 위험을 DB 조회만으로 판정한다.

    성분(ingredient) 단위가 정식 경로다 — `drug_ingredients`로 DUR 성분코드에 해소한 뒤
    `dur_ingredient_contraindications`(병용금기) / `dur_ingredient_effect_groups`(효능군중복)
    를 조회. 성분 경로가 재현 못 하는 품목쌍만 담은 소형 `residual_interactions`(217건)를
    항상 합친다. 등급은 결정적: contraindicated > duplicate_effect_group > safe.
    AI·ML 추론은 판정에 관여하지 않는다 (ML 시도 AUROC 0.48, archive/ml/README.md).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.drugs = DrugService(db)

    async def quick_check(
        self, drug_ids: list[uuid.UUID], user_id: uuid.UUID | None = None
    ) -> QuickCheckResponse:
        """병용금기·효능군중복(DUR, 항상)에 더해, `user_id`가 주어지면 그 사용자의
        복호화된 알레르기·출생연도로 알레르기 충돌·연령대 규칙도 함께 확인한다.
        둘 다 사용자 프로필의 정적 속성 대 약품 매칭이라 약품 쌍이 아니라 약품
        1개 단위 finding이라 `findings`(쌍 단위)와 분리된 리스트로 반환한다."""
        drugs = await self.drugs.get_drugs_by_ids(drug_ids)
        drug_id_list = list(drugs.keys())
        codes_by_drug = await self.drugs.get_ingredient_codes_for_drug_list(drug_id_list)

        ingredient_findings = await self._ingredient_findings(drugs, codes_by_drug)
        residual_findings = await self._residual_findings(drugs, drug_id_list)
        findings = self._merge(ingredient_findings, residual_findings)

        allergy_conflicts: list[AllergyConflict] = []
        age_cautions: list[AgeCaution] = []
        pregnancy_cautions: list[PregnancyCaution] = []
        if user_id is not None:
            user = await UserService(self.db).get_user(user_id)
            allergy_terms = getattr(user, "allergy_info", None) or []
            if allergy_terms:
                allergy_conflicts = await self._allergy_findings(drugs, allergy_terms)
            birth_year = getattr(user, "birth_year", None)
            if birth_year:
                age = date.today().year - birth_year
                age_cautions = await self._age_findings(drugs, codes_by_drug, age)
            if getattr(user, "is_pregnant", None) is True:
                pregnancy_cautions = await self._pregnancy_findings(drugs)

        contraindicated = [f for f in findings if f.interaction_type == "contraindicated"]
        duplicate_effect = [f for f in findings if f.interaction_type == "duplicate_effect_group"]
        age_taboo = [a for a in age_cautions if a.rule_type == "age_taboo"]
        elderly_caution = [a for a in age_cautions if a.rule_type == "elderly_caution"]
        return QuickCheckResponse(
            total_drugs=len(drugs),
            has_contraindication=bool(contraindicated),
            risk_level=_risk_level(findings, allergy_conflicts, age_cautions, pregnancy_cautions),
            contraindicated_count=len(contraindicated),
            duplicate_effect_group_count=len(duplicate_effect),
            age_taboo_count=len(age_taboo),
            elderly_caution_count=len(elderly_caution),
            pregnancy_taboo_count=len(pregnancy_cautions),
            findings=findings,
            allergy_conflicts=allergy_conflicts,
            age_cautions=age_cautions,
            pregnancy_cautions=pregnancy_cautions,
        )

    # ------------------------------------------------------------------ #
    # 알레르기 충돌 — 사용자 프로필(allergy_info) 대 약품 성분명 대조          #
    # ------------------------------------------------------------------ #

    async def _allergy_findings(
        self, drugs: dict[uuid.UUID, Drug], allergy_terms: list[str]
    ) -> list[AllergyConflict]:
        term_pairs = [(t, t.strip().lower()) for t in allergy_terms if t and t.strip()]
        if not term_pairs:
            return []
        names_by_drug = await self.drugs.get_ingredient_names_for_drug_list(list(drugs.keys()))

        conflicts: list[AllergyConflict] = []
        for drug_id, ingr_names in names_by_drug.items():
            for ingr in ingr_names:
                ingr_lower = ingr.strip().lower()
                if not ingr_lower:
                    continue
                for original_term, term_lower in term_pairs:
                    if term_lower in ingr_lower or ingr_lower in term_lower:
                        conflicts.append(AllergyConflict(
                            drug_id=drug_id, drug_name=_display_name(drugs[drug_id]),
                            matched_ingredient=ingr, matched_allergy_term=original_term,
                        ))
        return conflicts

    # ------------------------------------------------------------------ #
    # 연령대 규칙 — 특정연령대금기(age_taboo)·노인주의(elderly_caution)       #
    # ------------------------------------------------------------------ #

    async def _age_findings(
        self,
        drugs: dict[uuid.UUID, Drug],
        codes_by_drug: dict[uuid.UUID, set[str]],
        age: int,
    ) -> list[AgeCaution]:
        all_codes: set[str] = set()
        for codes in codes_by_drug.values():
            all_codes |= codes
        if not all_codes:
            return []

        rules_by_code: dict[str, list] = {}
        for rule in await self.drugs.get_ingr_age_caution_for_codes(all_codes):
            rules_by_code.setdefault(rule.ingr_code, []).append(rule)
        if not rules_by_code:
            return []

        cautions: list[AgeCaution] = []
        for drug_id, codes in codes_by_drug.items():
            for code in codes:
                for rule in rules_by_code.get(code, ()):
                    if rule.rule_type == "elderly_caution":
                        if age >= ELDERLY_AGE_THRESHOLD:
                            cautions.append(AgeCaution(
                                drug_id=drug_id, drug_name=_display_name(drugs[drug_id]),
                                rule_type="elderly_caution", prohibit_content=rule.prohibit_content,
                            ))
                    elif rule.rule_type == "age_taboo":
                        if rule.age_threshold is None or not rule.age_unit or not rule.age_direction:
                            # PROHBT_CONTENT에서 숫자 나이 기준을 못 뽑은 규칙 —
                            # 잘못된 임의 판정을 하느니 조용히 스킵한다(모델 docstring 참고).
                            continue
                        if _age_taboo_applies(age, rule.age_threshold, rule.age_unit, rule.age_direction):
                            cautions.append(AgeCaution(
                                drug_id=drug_id, drug_name=_display_name(drugs[drug_id]),
                                rule_type="age_taboo", prohibit_content=rule.prohibit_content,
                            ))
        return cautions

    # ------------------------------------------------------------------ #
    # 임부금기 — 임신 중으로 등록한 사용자 대 약품(품목 단위 규칙)              #
    # ------------------------------------------------------------------ #

    async def _pregnancy_findings(self, drugs: dict[uuid.UUID, Drug]) -> list[PregnancyCaution]:
        drug_by_seq = {d.item_seq: d for d in drugs.values() if d.item_seq}
        rules_by_seq: dict[str, list] = {}
        for rule in await self.drugs.get_pregnancy_taboo_for_item_seqs(set(drug_by_seq)):
            rules_by_seq.setdefault(rule.item_seq, []).append(rule)

        cautions: list[PregnancyCaution] = []
        for seq, rules in rules_by_seq.items():
            drug = drug_by_seq[seq]
            # 복합제는 성분별로 행이 따로 올 수 있다 — 약품 1개당 finding 1개로 합친다.
            contents = list(dict.fromkeys(r.prohibit_content for r in rules if r.prohibit_content))
            remarks = list(dict.fromkeys(r.remark for r in rules if r.remark))
            cautions.append(PregnancyCaution(
                drug_id=drug.id, drug_name=_display_name(drug),
                prohibit_content="\n".join(contents) or None,
                remark=" / ".join(remarks) or None,
            ))
        return cautions

    # ------------------------------------------------------------------ #
    # 성분(ingredient) 단위 — 정식 경로                                     #
    # ------------------------------------------------------------------ #

    async def _ingredient_findings(
        self, drugs: dict[uuid.UUID, Drug], codes_by_drug: dict[uuid.UUID, set[str]]
    ) -> list[QuickCheckFinding]:
        # 역인덱스 ingr_code -> {그 코드를 가진 drug_id}: 규칙/그룹마다 하는 조회를 O(1)로.
        code_to_drugs: dict[str, set[uuid.UUID]] = {}
        for drug_id, codes in codes_by_drug.items():
            for code in codes:
                code_to_drugs.setdefault(code, set()).add(drug_id)
        if not code_to_drugs:
            return []
        all_codes = set(code_to_drugs)

        findings: list[QuickCheckFinding] = []

        # 병용금기: 규칙 성분쌍의 양쪽을 서로 다른 약품이 각각 보유하면 finding
        for rule in await self.drugs.get_ingr_contraindications_for_codes(all_codes):
            mechanism = rule.prohibit_content or f"병용금기: {rule.ingr_kor_a} + {rule.ingr_kor_b}"
            for id1 in code_to_drugs.get(rule.ingr_code_a, ()):
                for id2 in code_to_drugs.get(rule.ingr_code_b, ()):
                    if id1 == id2:  # 복합제 한 알이 금기 성분 둘 다 보유 — 상호작용 아님
                        continue
                    findings.append(_finding(
                        drugs[id1], drugs[id2], "contraindicated",
                        mechanism, list(rule.risk_tags or []),
                        ingr_a=rule.ingr_kor_a, ingr_b=rule.ingr_kor_b,
                    ))

        # 효능군중복: 성분코드를 dur_seq로 묶어 서로 다른 약품 2개 이상이면 쌍 생성
        groups: dict[str, tuple[str, set[str]]] = {}
        for row in await self.drugs.get_ingr_effect_groups_for_codes(all_codes):
            _, codes = groups.setdefault(row.dur_seq, (row.effect_name, set()))
            codes.add(row.ingr_code)

        for effect_name, group_codes in groups.values():
            in_group = set().union(*(code_to_drugs.get(c, set()) for c in group_codes))
            if len(in_group) < 2:
                continue
            for id1, id2 in itertools.combinations(sorted(in_group, key=str), 2):
                findings.append(_finding(
                    drugs[id1], drugs[id2], "duplicate_effect_group",
                    f"효능군 중복: {effect_name}", [],
                ))

        # 동일 성분 중복 — 효능군 테이블에 없는 성분도 잡는다
        covered = {frozenset({f.drug1_id, f.drug2_id}) for f in findings
                   if f.interaction_type == "duplicate_effect_group"}
        shared = {c: ids for c, ids in code_to_drugs.items() if len(ids) >= 2}
        ingr_names = await self.drugs.get_ingredient_kor_for_codes(set(shared))
        for code, drug_ids in sorted(shared.items()):
            for id1, id2 in itertools.combinations(sorted(drug_ids, key=str), 2):
                pair = frozenset({id1, id2})
                if pair in covered:
                    continue
                covered.add(pair)
                findings.append(_finding(
                    drugs[id1], drugs[id2], "duplicate_effect_group",
                    f"동일 성분 중복: {ingr_names.get(code, code)}", [],
                ))

        return findings

    # ------------------------------------------------------------------ #
    # 잔여 폴백 — 성분 경로가 재현 못 하는 품목쌍(217건)                      #
    # ------------------------------------------------------------------ #

    async def _residual_findings(
        self, drugs: dict[uuid.UUID, Drug], drug_id_list: list[uuid.UUID]
    ) -> list[QuickCheckFinding]:
        rows = await self.drugs.get_residual_for_drug_list(drug_id_list)
        return [
            _finding(
                drugs[r.drug1_id], drugs[r.drug2_id],
                r.interaction_type, r.mechanism, [], source="residual",
            )
            for r in rows
            if r.drug1_id in drugs and r.drug2_id in drugs
        ]

    # ------------------------------------------------------------------ #
    # 병합 — 성분 우선, 잔여-only는 응답엔 포함하되 로그로 관측               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _merge(
        ingredient: list[QuickCheckFinding], residual: list[QuickCheckFinding]
    ) -> list[QuickCheckFinding]:
        merged: dict[tuple, QuickCheckFinding] = {}
        for f in ingredient:
            merged.setdefault((frozenset({f.drug1_id, f.drug2_id}), f.interaction_type), f)
        for f in residual:
            key = (frozenset({f.drug1_id, f.drug2_id}), f.interaction_type)
            if key in merged:
                continue
            merged[key] = f
            logger.warning(
                "quick_check residual-only finding: type=%s drugs=%s / %s "
                "(성분코드 미해소 약 — residual_interactions 폴백)",
                f.interaction_type, f.drug1_name, f.drug2_name,
            )
        return list(merged.values())


def _finding(
    d1: Drug, d2: Drug, interaction_type: str,
    mechanism: str | None, risk_tags: list[str], source: str = "ingredient",
    ingr_a: str | None = None, ingr_b: str | None = None,
) -> QuickCheckFinding:
    return QuickCheckFinding(
        drug1_id=d1.id, drug1_name=_display_name(d1),
        drug2_id=d2.id, drug2_name=_display_name(d2),
        interaction_type=interaction_type,
        mechanism=mechanism,
        risk_tags=risk_tags,
        source=source,
        ingr_a=ingr_a, ingr_b=ingr_b,
    )
