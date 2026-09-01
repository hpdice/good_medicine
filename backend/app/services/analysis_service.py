import itertools
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.drug import Drug
from app.schemas.analysis import QuickCheckFinding, QuickCheckResponse
from app.services.drug_service import DrugService


def _display_name(drug: Drug) -> str:
    return drug.simple_name or drug.item_name


def _risk_level(findings: list[QuickCheckFinding]) -> str:
    types = {f.interaction_type for f in findings}
    if "contraindicated" in types:
        return "critical"
    if "duplicate_effect_group" in types:
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

    async def quick_check(self, drug_ids: list[uuid.UUID]) -> QuickCheckResponse:
        drugs = await self.drugs.get_drugs_by_ids(drug_ids)
        drug_id_list = list(drugs.keys())
        codes_by_drug = await self.drugs.get_ingredient_codes_for_drug_list(drug_id_list)

        ingredient_findings = await self._ingredient_findings(drugs, codes_by_drug)
        residual_findings = await self._residual_findings(drugs, drug_id_list)
        findings = self._merge(ingredient_findings, residual_findings)

        contraindicated = [f for f in findings if f.interaction_type == "contraindicated"]
        duplicate_effect = [f for f in findings if f.interaction_type == "duplicate_effect_group"]
        return QuickCheckResponse(
            total_drugs=len(drugs),
            has_contraindication=bool(contraindicated),
            risk_level=_risk_level(findings),
            contraindicated_count=len(contraindicated),
            duplicate_effect_group_count=len(duplicate_effect),
            findings=findings,
        )

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
) -> QuickCheckFinding:
    return QuickCheckFinding(
        drug1_id=d1.id, drug1_name=_display_name(d1),
        drug2_id=d2.id, drug2_name=_display_name(d2),
        interaction_type=interaction_type,
        mechanism=mechanism,
        risk_tags=risk_tags,
        source=source,
    )
