import uuid

from pydantic import BaseModel, field_validator


class QuickCheckRequest(BaseModel):
    drug_ids: list[uuid.UUID]

    @field_validator("drug_ids")
    @classmethod
    def at_least_two(cls, v: list) -> list:
        if len(v) < 2:
            raise ValueError("병용금기 확인은 최소 2개 약품이 필요합니다.")
        if len(v) > 50:
            raise ValueError("최대 50개까지 확인 가능합니다.")
        return v


class QuickCheckFinding(BaseModel):
    drug1_id: uuid.UUID
    drug1_name: str
    drug2_id: uuid.UUID
    drug2_name: str
    interaction_type: str
    mechanism: str | None


class QuickCheckResponse(BaseModel):
    total_drugs: int
    has_contraindication: bool
    risk_level: str  # safe / critical
    contraindicated_count: int
    findings: list[QuickCheckFinding]
