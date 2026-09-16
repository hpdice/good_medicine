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
    # "자세히 보기" 토글용 — 병용금기가 실제로 어느 성분끼리 걸린 건지(drug1↔ingr_a, drug2↔ingr_b).
    # 성분 경로 병용금기(source=ingredient, interaction_type=contraindicated)일 때만 채워짐.
    ingr_a: str | None = None
    ingr_b: str | None = None


class AllergyConflict(BaseModel):
    """사용자가 등록한 알레르기 성분과 복약함 약품의 성분이 겹치는 경우.

    DUR 데이터가 아니라 사용자 프로필(`users.allergy_info`)과의 대조라서
    약품 쌍이 아니라 약품 1개 단위다."""

    drug_id: uuid.UUID
    drug_name: str
    matched_ingredient: str
    matched_allergy_term: str


class AgeCaution(BaseModel):
    """DUR 특정연령대금기(age_taboo)·노인주의(elderly_caution) — 약품 1개 단위.

    사용자가 등록한 출생연도로 계산한 나이가 규칙에 해당할 때만 생성된다."""

    drug_id: uuid.UUID
    drug_name: str
    rule_type: str  # age_taboo(금기) / elderly_caution(주의)
    prohibit_content: str | None


class QuickCheckResponse(BaseModel):
    total_drugs: int
    has_contraindication: bool
    risk_level: str  # safe / caution / critical
    contraindicated_count: int
    duplicate_effect_group_count: int = 0
    age_taboo_count: int = 0
    elderly_caution_count: int = 0
    findings: list[QuickCheckFinding]
    allergy_conflicts: list[AllergyConflict] = []
    age_cautions: list[AgeCaution] = []


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
