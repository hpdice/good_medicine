import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analysis import QuickCheckFinding, QuickCheckResponse
from app.services.drug_service import DrugService


class AnalysisService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def quick_check(self, drug_ids: list[uuid.UUID]) -> QuickCheckResponse:
        """DB만 사용하는 즉시 병용금기 확인 — Anthropic API 불필요."""
        drug_svc = DrugService(self.db)
        drugs = await drug_svc.get_drugs_by_ids(drug_ids)
        interactions = await drug_svc.get_interactions_for_drug_list(list(drugs.keys()))

        findings: list[QuickCheckFinding] = []
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

        contraindicated = [f for f in findings if f.interaction_type == "contraindicated"]
        risk_level = "critical" if contraindicated else "safe"

        return QuickCheckResponse(
            total_drugs=len(drugs),
            has_contraindication=bool(contraindicated),
            risk_level=risk_level,
            contraindicated_count=len(contraindicated),
            findings=findings,
        )
