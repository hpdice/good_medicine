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
    interaction_type: str  # contraindicated(확정,금기) / duplicate_effect_group(확정,주의)
    mechanism: str | None
    risk_tags: list[str] = []  # mechanism 문장에서 뽑은 위험/증상 태그 (예: ["출혈위험", "신독성"])
    source: str = "ingredient"  # ingredient(성분 단위 정식 판정) / residual(성분코드 미해소 약 폴백)


class QuickCheckResponse(BaseModel):
    total_drugs: int
    has_contraindication: bool
    risk_level: str  # safe / caution / critical
    contraindicated_count: int
    duplicate_effect_group_count: int = 0
    findings: list[QuickCheckFinding]


class AnalysisGuideRequest(QuickCheckRequest):
    """quick_check와 동일한 drug_ids 검증(최소 2개, 최대 50개)을 그대로 재사용."""


class AnalysisGuideResponse(BaseModel):
    risk_level: str  # safe / caution / critical — quick_check가 확정한 값 그대로, AI가 바꾸지 않음
    guide_text: str
    is_ai_generated: bool = True
    disclaimer: str = (
        "이 설명은 AI가 생성한 참고용 안내이며 의학적 진단이 아닙니다. "
        "위급하거나 확신이 서지 않으면 반드시 의사·약사와 상담하세요."
    )
