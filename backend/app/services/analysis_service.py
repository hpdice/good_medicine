import itertools
import re
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import get_encryptor
from app.core.logging import logger
from app.models.drug import Drug
from app.models.dur_ingredient_rule import DurIngredientAgeCaution, DurIngredientDoseCaution
from app.models.medicine_box import MedicineBoxEntry
from app.schemas.analysis import (
    AgeCaution,
    AllergyConflict,
    DoseCaution,
    PregnancyCaution,
    QuickCheckFinding,
    QuickCheckResponse,
)
from app.services.drug_service import DrugService
from app.services.user_service import UserService

# 노인주의 엔드포인트(getOdsnAtentInfoList03) 자체가 "노인 대상" 성분만 다루므로
# 개별 규칙에 나이 기준이 없다 — 통상적인 한국 노인 기준(만 65세)을 고정값으로 쓴다.
ELDERLY_AGE_THRESHOLD = 65

# 용량주의 규칙의 제형(FORM_NAME)을 나누는 구분자 — '정제/캡슐', '서방성캡슐제, 펠렛'
_FORM_SEP = re.compile(r"[/,]")


def _display_name(drug: Drug) -> str:
    return drug.simple_name or drug.item_name


def _age_taboo_applies(age_years: int, threshold: int, unit: str, direction: str) -> bool:
    """`age_threshold`/`age_unit`/`age_direction`으로 나이 조건을 계산한다. 생년월일이 아니라
    출생연도만 수집하므로 "개월"·"주" 단위 기준은 근사치(threshold/12, /52)로 연 단위 비교한다."""
    limit = threshold / 12 if unit == "개월" else threshold / 52 if unit == "주" else threshold
    return {
        "미만": age_years < limit,
        "이상": age_years >= limit,
        "이하": age_years <= limit,
        "초과": age_years > limit,
    }.get(direction, False)


def _age_rule_applies(rule: DurIngredientAgeCaution, age_years: int) -> bool:
    """이 나이의 사용자에게 연령 규칙이 걸리는가. 노인주의는 엔드포인트 자체가 "노인 대상"이라
    고정 기준(만 65세)만 본다. 특정연령대금기는 나이 기준 세 필드가 모두 파싱됐을 때만 계산하고,
    숫자 기준을 못 뽑은 규칙은 잘못된 임의 판정을 하느니 걸지 않는다(모델 docstring 참고)."""
    if rule.rule_type == "elderly_caution":
        return age_years >= ELDERLY_AGE_THRESHOLD
    if rule.rule_type == "age_taboo" and rule.age_threshold is not None and rule.age_unit and rule.age_direction:
        return _age_taboo_applies(age_years, rule.age_threshold, rule.age_unit, rule.age_direction)
    return False


def _risk_level(
    findings: list[QuickCheckFinding],
    allergy_conflicts: list[AllergyConflict],
    age_cautions: list[AgeCaution],
    pregnancy_cautions: Sequence[PregnancyCaution] = (),
    dose_cautions: Sequence[DoseCaution] = (),
) -> str:
    types = {f.interaction_type for f in findings}
    has_age_taboo = any(a.rule_type == "age_taboo" for a in age_cautions)
    has_elderly_caution = any(a.rule_type == "elderly_caution" for a in age_cautions)
    if "contraindicated" in types or allergy_conflicts or has_age_taboo or pregnancy_cautions:
        return "critical"
    # 용량주의는 DUR에서 '주의' 등급이다(병용금기처럼 금기가 아님)
    if "duplicate_ingredient" in types or "duplicate_effect_group" in types or has_elderly_caution or dose_cautions:
        return "caution"
    return "safe"


def _dose_form_kind(form: str) -> str | None:
    """제형명 → 정제(tablet) / 캡슐(capsule) / 서방형(sr). 함량을 아는 약은 내복 정·캡슐뿐이라 셋으로만 가른다.
    같은 성분도 제형마다 하루 최대량이 다르다(클로미프라민: 조루증용 정제 15mg, 우울증용 캡슐은 별도)."""
    if "서방" in form:
        return "sr"
    if "캡슐" in form:
        return "capsule"
    return "tablet" if "정" in form else None


def _rule_fits_form(rule_form: str, drug_kind: str | None) -> bool:
    """규칙 제형이 비었거나 '고형제'(아세트아미노펜 '고형제/반고형제/액제')면 모든 정·캡슐에 해당한다.
    그 밖에는 약의 제형을 알고 그 제형이 규칙에 들어 있을 때만 해당한다."""
    if not rule_form or "고형제" in rule_form:
        return True
    return drug_kind is not None and drug_kind in {_dose_form_kind(t) for t in _FORM_SEP.split(rule_form)}


def _single_form_kind(forms: Iterable[str]) -> str | None:
    """심평원 제형명들 → 약 하나의 제형. 일반명코드가 여럿이라 제형이 갈리면 모른다(None)."""
    found = {_dose_form_kind(f) for f in forms} - {None}
    return found.pop() if len(found) == 1 else None


@dataclass
class _DoseInputs:
    """용량주의 판정 재료. `daily_mg`는 약 → {성분코드: 하루 mg}(복용량·함량을 둘 다 아는 약만)."""
    drugs: dict[uuid.UUID, Drug]
    codes_by_drug: dict[uuid.UUID, set[str]]
    daily_mg: dict[uuid.UUID, dict[str, float]]
    kinds: dict[uuid.UUID, str | None]
    names: dict[str, str]

    def caution(self, counted: list[uuid.UUID], uncounted: list[uuid.UUID], rule: DurIngredientDoseCaution,
                code: str, daily: float, limit: float, scope: str) -> DoseCaution:
        return DoseCaution(
            drug_ids=counted, drug_names=[_display_name(self.drugs[d]) for d in counted],
            ingredient=self.names.get(code) or rule.ingr_kor or code, daily_mg=round(daily, 3), max_daily_mg=limit,
            scope=scope, prohibit_content=rule.prohibit_content,
            uncounted_drug_names=[_display_name(self.drugs[d]) for d in uncounted],
        )


def _total_dose_cautions(
    dose: _DoseInputs, single_rules: list[DurIngredientDoseCaution],
) -> tuple[list[DoseCaution], set[tuple[uuid.UUID, str]]]:
    """단일제 규칙 — 같은 성분이 든 약들의 하루 양을 합쳐 비교. 경고와 경고에 들어간 (약, 성분코드)를 돌려준다."""
    by_code: dict[str, list[DurIngredientDoseCaution]] = {}
    for rule in single_rules:
        if rule.ingr_code in (rule.limits_mg or {}):
            by_code.setdefault(rule.ingr_code, []).append(rule)

    cautions: list[DoseCaution] = []
    flagged: set[tuple[uuid.UUID, str]] = set()
    for code, group in sorted(by_code.items()):
        counted: list[uuid.UUID] = []
        uncounted: list[uuid.UUID] = []
        rule_by_limit: dict[float, DurIngredientDoseCaution] = {}
        for drug_id in sorted((d for d, codes in dose.codes_by_drug.items() if code in codes), key=str):
            # 이 약의 제형에 해당하는 상한이 하나로 정해질 때만 센다(없거나 여럿이면 이 약은 이 판정 밖)
            fitting = {(r.limits_mg or {})[code]: r for r in group if _rule_fits_form(r.form_name, dose.kinds[drug_id])}
            if len(fitting) != 1:
                continue
            if code in dose.daily_mg.get(drug_id, {}):
                counted.append(drug_id)
                rule_by_limit.update(fitting)
            else:
                uncounted.append(drug_id)
        if not counted:
            continue
        # 제형이 다른 약끼리 상한이 다르면 큰 쪽으로 비교한다(오경고보다 놓치는 쪽을 택함)
        limit = max(rule_by_limit)
        total = sum(dose.daily_mg[d][code] for d in counted)
        if total > limit:
            cautions.append(dose.caution(counted, uncounted, rule_by_limit[limit], code, total, limit, "total"))
            flagged |= {(d, code) for d in counted}
    return cautions, flagged


def _product_dose_cautions(
    dose: _DoseInputs, mix_rules: list[DurIngredientDoseCaution], flagged: set[tuple[uuid.UUID, str]],
) -> list[DoseCaution]:
    """복합제 규칙 — 조성이 규칙과 정확히 같은 약 한 품목만. 이미 합산 경고에 든 (약, 성분)은 다시 내지 않는다."""
    cautions: list[DoseCaution] = []
    for rule in mix_rules:
        composition = {rule.ingr_code, *rule.mix_codes.split(",")}
        for drug_id, codes in dose.codes_by_drug.items():
            if codes != composition or drug_id not in dose.daily_mg or not _rule_fits_form(rule.form_name, dose.kinds[drug_id]):
                continue
            for code, limit in (rule.limits_mg or {}).items():
                mg = dose.daily_mg[drug_id].get(code)
                if mg is not None and mg > limit and (drug_id, code) not in flagged:
                    cautions.append(dose.caution([drug_id], [], rule, code, mg, limit, "product"))
                    flagged.add((drug_id, code))
    return cautions


def _drugs_by_code(codes_by_drug: dict[uuid.UUID, set[str]]) -> dict[str, set[uuid.UUID]]:
    """역인덱스 성분코드 -> {그 코드를 가진 약}. 규칙/그룹마다 하는 "이 성분을 가진 약이 있나" 조회를 O(1)로."""
    index: dict[str, set[uuid.UUID]] = {}
    for drug_id, codes in codes_by_drug.items():
        for code in codes:
            index.setdefault(code, set()).add(drug_id)
    return index


class AnalysisService:
    """복약함 약품 목록의 병용 위험을 DB 조회만으로 판정한다.

    성분(ingredient) 단위가 정식 경로다 — `drug_ingredients`로 DUR 성분코드에 해소한 뒤
    `dur_ingredient_contraindications`(병용금기) / `dur_ingredient_effect_groups`(효능군중복)
    를 조회. 성분 경로가 재현 못 하는 품목쌍만 담은 소형 `residual_interactions`(217건)를
    항상 합친다. 등급은 결정적: contraindicated > duplicate_ingredient/duplicate_effect_group > safe.
    AI·ML 추론은 판정에 관여하지 않는다.
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

        allergy_conflicts, age_cautions, pregnancy_cautions = await self._user_findings(
            user_id, drugs, codes_by_drug
        )
        dose_cautions = await self._dose_findings(user_id, drugs, codes_by_drug) if user_id else []

        kinds = Counter(f.interaction_type for f in findings)
        age_kinds = Counter(a.rule_type for a in age_cautions)
        return QuickCheckResponse(
            total_drugs=len(drugs),
            has_contraindication=kinds["contraindicated"] > 0,
            risk_level=_risk_level(findings, allergy_conflicts, age_cautions, pregnancy_cautions, dose_cautions),
            contraindicated_count=kinds["contraindicated"],
            duplicate_effect_group_count=kinds["duplicate_effect_group"],
            duplicate_ingredient_count=kinds["duplicate_ingredient"],
            age_taboo_count=age_kinds["age_taboo"],
            elderly_caution_count=age_kinds["elderly_caution"],
            pregnancy_taboo_count=len(pregnancy_cautions),
            dose_caution_count=len(dose_cautions),
            findings=findings,
            allergy_conflicts=allergy_conflicts,
            age_cautions=age_cautions,
            pregnancy_cautions=pregnancy_cautions,
            dose_cautions=dose_cautions,
        )

    async def _user_findings(
        self,
        user_id: uuid.UUID | None,
        drugs: dict[uuid.UUID, Drug],
        codes_by_drug: dict[uuid.UUID, set[str]],
    ) -> tuple[list[AllergyConflict], list[AgeCaution], list[PregnancyCaution]]:
        """로그인 사용자의 알레르기·출생연도·임신 여부로 하는 판정. 정보가 비어 있거나 `user_id`가 없으면
        해당 판정은 건너뛴다(빈 목록)."""
        if user_id is None:
            return [], [], []
        user = await UserService(self.db).get_user(user_id)
        allergy_terms = getattr(user, "allergy_info", None) or []
        birth_year = getattr(user, "birth_year", None)
        allergy = await self._allergy_findings(drugs, allergy_terms) if allergy_terms else []
        age = (
            await self._age_findings(drugs, codes_by_drug, date.today().year - birth_year)
            if birth_year else []
        )
        pregnancy = await self._pregnancy_findings(drugs) if getattr(user, "is_pregnant", None) is True else []
        return allergy, age, pregnancy

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

        return [
            AgeCaution(
                drug_id=drug_id, drug_name=_display_name(drugs[drug_id]),
                rule_type=rule.rule_type, prohibit_content=rule.prohibit_content,
            )
            for drug_id, codes in codes_by_drug.items()
            for code in codes
            for rule in rules_by_code.get(code, ())
            if _age_rule_applies(rule, age)
        ]

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
    # 용량주의 — 복약함에 적은 복용량 × 1개당 함량 대 DUR 1일 최대 투여량        #
    # ------------------------------------------------------------------ #

    async def _daily_units(self, user_id: uuid.UUID, drug_ids: set[uuid.UUID]) -> dict[uuid.UUID, float]:
        """약품 ID → 하루에 먹는 개수(1회 개수 × 1일 횟수). 복약함에 둘 다 적힌 약만."""
        enc = get_encryptor()
        rows = await self.db.execute(select(MedicineBoxEntry.payload_encrypted).where(
            MedicineBoxEntry.user_id == user_id, MedicineBoxEntry.is_current == True,  # noqa: E712
        ))
        units: dict[uuid.UUID, float] = {}
        for (token,) in rows.all():
            try:
                payload = enc.decrypt(token)
            except Exception:  # 손상된 항목 하나 때문에 판정 전체가 실패하지 않게 건너뛴다
                logger.warning("복약함 항목 복호화 실패 — 용량 판정에서 제외")
                continue
            per_intake, per_day = payload.get("units_per_intake"), payload.get("times_per_day")
            drug_id = uuid.UUID(payload["drug_id"])
            if drug_id in drug_ids and per_intake and per_day:
                units[drug_id] = float(per_intake) * int(per_day)
        return units

    async def _dose_findings(
        self, user_id: uuid.UUID, drugs: dict[uuid.UUID, Drug], codes_by_drug: dict[uuid.UUID, set[str]]
    ) -> list[DoseCaution]:
        """① 단일제 규칙: 같은 성분이 든 약들의 하루 양을 합쳐 그 성분의 하루 최대량과 비교(아세트아미노펜이 든
        감기약 + 해열제). ② 복합제 규칙: 조성이 규칙과 정확히 같은 약 한 품목의 하루 양을 그 기준과 비교.
        복용량이나 함량을 모르는 약은 합치지 못해 실제 양보다 적게 잡히므로, 넘을 때만 경고하고 그 약 이름을 함께 알린다."""
        daily_units = await self._daily_units(user_id, set(drugs))
        if not daily_units or not codes_by_drug:
            return []
        amounts = await self.drugs.get_ingredient_amounts_for_drug_list(list(daily_units))
        rules = await self.drugs.get_ingr_dose_cautions_for_codes(set().union(*codes_by_drug.values()))
        forms = await self.drugs.get_hira_form_names({d.item_seq for d in drugs.values() if d.item_seq})
        dose = _DoseInputs(
            drugs=drugs,
            codes_by_drug=codes_by_drug,
            daily_mg={
                drug_id: {code: mg * daily_units[drug_id] for code, mg in per_code.items()}
                for drug_id, per_code in amounts.items()
            },
            kinds={drug_id: _single_form_kind(forms.get(drug.item_seq, ())) for drug_id, drug in drugs.items()},
            names=await self.drugs.get_ingredient_kor_for_codes({c for r in rules for c in (r.limits_mg or {})}),
        )
        cautions, flagged = _total_dose_cautions(dose, [r for r in rules if not r.mix_codes])
        return cautions + _product_dose_cautions(dose, [r for r in rules if r.mix_codes], flagged)

    # ------------------------------------------------------------------ #
    # 성분(ingredient) 단위 — 정식 경로                                     #
    # ------------------------------------------------------------------ #

    async def _ingredient_findings(
        self, drugs: dict[uuid.UUID, Drug], codes_by_drug: dict[uuid.UUID, set[str]]
    ) -> list[QuickCheckFinding]:
        code_to_drugs = _drugs_by_code(codes_by_drug)
        if not code_to_drugs:
            return []
        return [
            *await self._contraindication_findings(drugs, code_to_drugs),
            *await self._same_ingredient_findings(drugs, code_to_drugs),
            *await self._effect_group_findings(drugs, code_to_drugs),
        ]

    async def _contraindication_findings(
        self, drugs: dict[uuid.UUID, Drug], code_to_drugs: dict[str, set[uuid.UUID]]
    ) -> list[QuickCheckFinding]:
        """병용금기: 규칙 성분쌍의 양쪽을 서로 다른 약품이 각각 보유하면 finding."""
        findings: list[QuickCheckFinding] = []
        for rule in await self.drugs.get_ingr_contraindications_for_codes(set(code_to_drugs)):
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
        return findings

    async def _same_ingredient_findings(
        self, drugs: dict[uuid.UUID, Drug], code_to_drugs: dict[str, set[uuid.UUID]]
    ) -> list[QuickCheckFinding]:
        """동일 성분 중복: 같은 성분코드를 가진 서로 다른 약품 쌍 (효능군 테이블 유무와 무관)."""
        shared = {c: ids for c, ids in code_to_drugs.items() if len(ids) >= 2}
        ingr_names = await self.drugs.get_ingredient_kor_for_codes(set(shared))
        findings: list[QuickCheckFinding] = []
        for code, drug_ids in sorted(shared.items()):
            name = ingr_names.get(code, code)
            for id1, id2 in itertools.combinations(sorted(drug_ids, key=str), 2):
                findings.append(_finding(
                    drugs[id1], drugs[id2], "duplicate_ingredient",
                    f"두 약 모두 {name} 성분이에요. 함께 복용하면 같은 성분이 중복돼 과량이 될 수 있어요.",
                    [],
                ))
        return findings

    async def _effect_group_findings(
        self, drugs: dict[uuid.UUID, Drug], code_to_drugs: dict[str, set[uuid.UUID]]
    ) -> list[QuickCheckFinding]:
        """효능군중복: 성분코드를 **효능군 + 계열**(예: 혈압강하작용의약품 / ARB)로 묶어 서로 다른 약품
        2개 이상이면 쌍 생성. `dur_seq`는 성분마다 따로 붙는 번호라 묶음 키로 쓰지 않는다.
        계열이 다르면(ARB + CCB, 메트포르민 + 설포닐우레아) 같은 효능군이어도 중복이 아니다."""
        groups: dict[tuple[str, str | None], set[str]] = {}
        for row in await self.drugs.get_ingr_effect_groups_for_codes(set(code_to_drugs)):
            groups.setdefault((row.effect_name, row.sers_name), set()).add(row.ingr_code)

        findings: list[QuickCheckFinding] = []
        for (effect_name, sers_name), group_codes in groups.items():
            in_group = set().union(*(code_to_drugs.get(c, set()) for c in group_codes))
            label = f"{effect_name} · {sers_name}" if sers_name else effect_name
            for id1, id2 in itertools.combinations(sorted(in_group, key=str), 2):
                findings.append(_finding(
                    drugs[id1], drugs[id2], "duplicate_effect_group",
                    f"효능군 중복: {label}", [],
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
    # 병합 — 같은 쌍을 두 번 경고하지 않는다 (중복 억제 규칙은 여기 한 곳)      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _merge(
        ingredient: list[QuickCheckFinding], residual: list[QuickCheckFinding]
    ) -> list[QuickCheckFinding]:
        """① 같은 약 쌍·같은 유형은 먼저 온 것만 남긴다(성분 경로가 잔여보다 앞).
        ② 같은 쌍이 이미 "동일 성분 중복"이면 "효능군 중복"은 생략한다(같은 말을 두 번 하지 않음).
        잔여 경로에서만 나온 finding은 응답엔 넣되 로그로 남긴다."""
        merged: dict[tuple, QuickCheckFinding] = {}
        for f in (*ingredient, *residual):
            merged.setdefault((frozenset({f.drug1_id, f.drug2_id}), f.interaction_type), f)

        kept = [
            f for (pair, kind), f in merged.items()
            if not (kind == "duplicate_effect_group" and (pair, "duplicate_ingredient") in merged)
        ]
        for f in kept:
            if f.source == "residual":
                logger.warning(
                    "quick_check residual-only finding: type=%s drugs=%s / %s "
                    "(성분코드 미해소 약 — residual_interactions 폴백)",
                    f.interaction_type, f.drug1_name, f.drug2_name,
                )
        return kept


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
