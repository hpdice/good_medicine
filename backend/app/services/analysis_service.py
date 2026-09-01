import itertools
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.schemas.analysis import QuickCheckFinding, QuickCheckResponse
from app.services.drug_service import DrugService


class AnalysisService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def quick_check(self, drug_ids: list[uuid.UUID]) -> QuickCheckResponse:
        """DB만 보고 바로 판정 — 병용금기·효능군중복 둘 다 식약처가 확정한
        공식 데이터라 AI·ML 추정 없이 조회만 하면 된다.

        판정은 **성분(ingredient) 단위**가 정식 경로다(`drug_ingredients` +
        `dur_ingredient_*`). 여기에 소형 `residual_interactions`(217건 — 성분 경로가
        재현하지 못하는 품목쌍만)를 항상 합쳐 본다. 구 품목 테이블
        (`drug_interactions` 331K행)은 성분 경로가 그 탐지의 100.0%를 재현함이
        확인되어 0006 마이그레이션에서 폐기됐다.

        ML로 DUR 미커버 쌍을 추정하는 시도는 AUROC 0.48(랜덤 수준)로 실익이
        없어 서빙에서 제외됨 (archive/ml/README.md).
        """
        drug_svc = DrugService(self.db)
        drugs = await drug_svc.get_drugs_by_ids(drug_ids)
        drug_id_list = list(drugs.keys())

        def _name(drug) -> str:
            return drug.simple_name or drug.item_name

        codes_by_drug = await drug_svc.get_ingredient_codes_for_drug_list(drug_id_list)
        ingredient_findings = await self._ingredient_findings(drug_svc, drugs, codes_by_drug, _name)

        # residual_interactions는 "성분 경로가 재현 못 하는 쌍"만 담으므로, 그 약들이
        # 나중에 성분코드를 얻어도(build_drug_ingredients 등) 규칙은 여전히 없다.
        # 217행짜리 인덱스 조회라 항상 합쳐 본다 (조건부 스킵은 미탐 위험).
        residual_findings = await self._residual_findings(drug_svc, drugs, drug_id_list, _name)

        findings = self._merge_findings(ingredient_findings, residual_findings)

        contraindicated = [f for f in findings if f.interaction_type == "contraindicated"]
        duplicate_effect = [f for f in findings if f.interaction_type == "duplicate_effect_group"]

        if contraindicated:
            risk_level = "critical"
        elif duplicate_effect:
            risk_level = "caution"
        else:
            risk_level = "safe"

        return QuickCheckResponse(
            total_drugs=len(drugs),
            has_contraindication=bool(contraindicated),
            risk_level=risk_level,
            contraindicated_count=len(contraindicated),
            duplicate_effect_group_count=len(duplicate_effect),
            findings=findings,
        )

    # ------------------------------------------------------------------ #
    # 성분(ingredient) 단위 — 정식 경로                                     #
    # ------------------------------------------------------------------ #

    async def _ingredient_findings(
        self, drug_svc: DrugService, drugs: dict,
        codes_by_drug: dict[uuid.UUID, set[str]], _name,
    ) -> list[QuickCheckFinding]:
        # 역인덱스: ingr_code -> {그 코드를 가진 drug_id}. 규칙/그룹마다 codes_by_drug를
        # 전부 스캔하던 걸 O(1) 조회로 바꾼다.
        code_to_drugs: dict[str, set[uuid.UUID]] = {}
        for did, codes in codes_by_drug.items():
            for code in codes:
                code_to_drugs.setdefault(code, set()).add(did)
        if not code_to_drugs:
            return []
        all_codes = set(code_to_drugs)

        findings: list[QuickCheckFinding] = []

        # 병용금기: 규칙 성분쌍의 양쪽을 서로 다른 약품이 각각 보유하면 finding
        for rule in await drug_svc.get_ingr_contraindications_for_codes(all_codes):
            for id1 in code_to_drugs.get(rule.ingr_code_a, ()):
                for id2 in code_to_drugs.get(rule.ingr_code_b, ()):
                    if id1 == id2:  # 복합제 한 알이 금기 성분 둘 다 보유 — 상호작용 아님
                        continue
                    d1, d2 = drugs[id1], drugs[id2]
                    mech = rule.prohibit_content or f"병용금기: {rule.ingr_kor_a} + {rule.ingr_kor_b}"
                    findings.append(QuickCheckFinding(
                        drug1_id=id1, drug1_name=_name(d1),
                        drug2_id=id2, drug2_name=_name(d2),
                        interaction_type="contraindicated",
                        mechanism=mech,
                        risk_tags=list(rule.risk_tags or []),
                        source="ingredient",
                    ))

        # 효능군중복: 성분코드를 dur_seq로 묶어 서로 다른 약품 2개 이상이면 쌍 생성
        by_dur_seq: dict[str, dict] = {}
        for row in await drug_svc.get_ingr_effect_groups_for_codes(all_codes):
            entry = by_dur_seq.setdefault(
                row.dur_seq, {"effect_name": row.effect_name, "codes": set()}
            )
            entry["codes"].add(row.ingr_code)

        for entry in by_dur_seq.values():
            drugs_in_group: set[uuid.UUID] = set()
            for code in entry["codes"]:
                drugs_in_group |= code_to_drugs.get(code, set())
            if len(drugs_in_group) < 2:
                continue
            for id1, id2 in itertools.combinations(sorted(drugs_in_group, key=str), 2):
                d1, d2 = drugs[id1], drugs[id2]
                findings.append(QuickCheckFinding(
                    drug1_id=id1, drug1_name=_name(d1),
                    drug2_id=id2, drug2_name=_name(d2),
                    interaction_type="duplicate_effect_group",
                    mechanism=f"효능군 중복: {entry['effect_name']}",
                    source="ingredient",
                ))

        return findings

    # ------------------------------------------------------------------ #
    # 잔여 폴백 — 성분코드 미해소 약이 낀 ~217쌍만 담은 residual_interactions #
    # ------------------------------------------------------------------ #

    async def _residual_findings(
        self, drug_svc: DrugService, drugs: dict, drug_id_list: list[uuid.UUID], _name
    ) -> list[QuickCheckFinding]:
        findings: list[QuickCheckFinding] = []
        for row in await drug_svc.get_residual_for_drug_list(drug_id_list):
            d1 = drugs.get(row.drug1_id)
            d2 = drugs.get(row.drug2_id)
            if not d1 or not d2:
                continue
            findings.append(QuickCheckFinding(
                drug1_id=row.drug1_id, drug1_name=_name(d1),
                drug2_id=row.drug2_id, drug2_name=_name(d2),
                interaction_type=row.interaction_type,
                mechanism=row.mechanism,
                source="residual",
            ))
        return findings

    # ------------------------------------------------------------------ #
    # 병합 — 성분 우선, 잔여-only는 응답엔 포함하되 로그로 관측               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _merge_findings(
        ingredient_findings: list[QuickCheckFinding],
        residual_findings: list[QuickCheckFinding],
    ) -> list[QuickCheckFinding]:
        merged: dict[tuple, QuickCheckFinding] = {}
        for f in ingredient_findings:
            key = (frozenset({f.drug1_id, f.drug2_id}), f.interaction_type)
            merged.setdefault(key, f)

        for f in residual_findings:
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
