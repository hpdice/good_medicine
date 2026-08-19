import itertools
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analysis import QuickCheckFinding, QuickCheckResponse
from app.services.drug_service import DrugService


class AnalysisService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def quick_check(self, drug_ids: list[uuid.UUID]) -> QuickCheckResponse:
        """DB만 사용하는 즉시 확인 — 병용금기·효능군중복 모두 식약처가 확정한
        공식 데이터를 직접 조회한다 (Anthropic API·ML 추정 불필요).

        ML 기반 미커버 쌍 추정은 시도했으나(archive/ml/README.md), 완전히
        새로운 계열 조합에 대해서는 AUROC 0.48(무작위 수준)이고, 신뢰도
        0.85 이상으로 잡히는 쌍조차 전부 이미 class_pair_density > 0인
        (=SQL로 이미 알 수 있는) 부분집합이라 실질적으로 추가 가치가
        없어 서빙에서 제외했다.
        """
        drug_svc = DrugService(self.db)
        drugs = await drug_svc.get_drugs_by_ids(drug_ids)

        findings: list[QuickCheckFinding] = []

        interactions = await drug_svc.get_interactions_for_drug_list(list(drugs.keys()))
        for inter in interactions:
            d1 = drugs.get(inter.drug1_id)
            d2 = drugs.get(inter.drug2_id)
            if not d1 or not d2:
                continue
            findings.append(QuickCheckFinding(
                drug1_id=inter.drug1_id,
                drug1_name=d1.simple_name or d1.item_name,
                drug2_id=inter.drug2_id,
                drug2_name=d2.simple_name or d2.item_name,
                interaction_type=inter.interaction_type,
                mechanism=inter.mechanism,
            ))

        effect_groups = await drug_svc.get_effect_groups_for_drug_list(list(drugs.keys()))
        by_dur_seq: dict[str, list] = {}
        for eg in effect_groups:
            by_dur_seq.setdefault(eg.dur_seq, []).append(eg)
        for dur_seq, members in by_dur_seq.items():
            member_drug_ids = {m.drug_id for m in members}
            if len(member_drug_ids) < 2:
                continue
            effect_name = members[0].effect_name
            for id1, id2 in itertools.combinations(sorted(member_drug_ids, key=str), 2):
                d1, d2 = drugs.get(id1), drugs.get(id2)
                if not d1 or not d2:
                    continue
                findings.append(QuickCheckFinding(
                    drug1_id=id1,
                    drug1_name=d1.simple_name or d1.item_name,
                    drug2_id=id2,
                    drug2_name=d2.simple_name or d2.item_name,
                    interaction_type="duplicate_effect_group",
                    mechanism=f"효능군 중복: {effect_name}",
                ))

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
