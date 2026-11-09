import uuid

from pydantic import BaseModel, field_validator


class QuickCheckRequest(BaseModel):
    drug_ids: list[uuid.UUID]

    @field_validator("drug_ids")
    @classmethod
    def at_least_one(cls, v: list) -> list:
        # 약 하나만으로도 걸리는 판정(용량 초과·건강 상태 금기·나이·임신)이 있어 1개부터 받는다
        if not v:
            raise ValueError("확인할 약품이 없습니다.")
        if len(v) > 50:
            raise ValueError("최대 50개까지 확인 가능합니다.")
        return v


class QuickCheckFinding(BaseModel):
    drug1_id: uuid.UUID
    drug1_name: str
    drug2_id: uuid.UUID
    drug2_name: str
    interaction_type: str  # contraindicated(확정,금기) / duplicate_ingredient(동일 성분,주의) / duplicate_effect_group(효능군,주의)
    mechanism: str | None
    risk_tags: list[str] = []  # mechanism 문장에서 뽑은 위험/증상 태그 (예: ["출혈위험", "신독성"])
    source: str = "ingredient"  # ingredient(성분 단위 정식 판정) / residual(성분코드 미해소 약 폴백)
    # "자세히 보기" 토글용 — 병용금기가 실제로 어느 성분끼리 걸린 건지(drug1↔ingr_a, drug2↔ingr_b).
    # 성분 경로 병용금기(source=ingredient, interaction_type=contraindicated)일 때만 채워짐.
    ingr_a: str | None = None
    ingr_b: str | None = None


class ConditionTaboo(BaseModel):
    """사용자가 등록한 건강 상태가 약 허가사항의 "다음 환자에는 투여하지 말 것" 항목에 있는 경우 — 약품 1개 단위.

    `sentence`는 그 항목의 원문이고, 의학적 해석 없이 글자가 들어 있을 때만 만든다(`condition_taboo.py`)."""

    drug_id: uuid.UUID
    drug_name: str
    condition: str
    sentence: str


class AgeCaution(BaseModel):
    """DUR 특정연령대금기(age_taboo)·노인주의(elderly_caution) — 약품 1개 단위.

    사용자가 등록한 출생연도로 계산한 나이가 규칙에 해당할 때만 생성된다."""

    drug_id: uuid.UUID
    drug_name: str
    rule_type: str  # age_taboo(금기) / elderly_caution(주의)
    prohibit_content: str | None


class PregnancyCaution(BaseModel):
    """DUR 임부금기 — 약품 1개 단위. 사용자가 임신 중으로 등록했을 때만 생성된다.

    `prohibit_content`는 등급(1·2등급)·근거(동물실험·기형 보고)가 섞인 원문,
    `remark`는 적용 범위(예: '경구', '제2형 당뇨병')다 — 둘 다 그대로 보여준다."""

    drug_id: uuid.UUID
    drug_name: str
    prohibit_content: str | None
    remark: str | None = None


class DoseCaution(BaseModel):
    """DUR 용량주의 — 하루에 먹는 성분 양이 식약처가 정한 1일 최대 투여량을 넘는 경우.

    복약함에 적은 복용량(1회 개수 × 1일 횟수)과 정·캡슐 1개당 함량으로 계산한다. `scope`가 total이면
    같은 성분이 든 여러 약을 합친 양(예: 아세트아미노펜 4,000mg), product면 복합제 한 품목에 정해진 기준이다.
    `uncounted_drug_names`는 이 성분이 들었지만 복용량이나 함량을 몰라 합치지 못한 약 — 실제 양은 더 많을 수 있다."""

    drug_ids: list[uuid.UUID]
    drug_names: list[str]
    ingredient: str
    daily_mg: float
    max_daily_mg: float
    scope: str  # total / product
    prohibit_content: str | None = None
    uncounted_drug_names: list[str] = []


class UnresolvedDrug(BaseModel):
    """DUR 성분코드가 없어 성분 규칙(병용금기·동일 성분·효능군·연령·하루 용량)을 적용하지 못한 약.

    `risk_level`이 safe여도 이 약은 "확인된 위험이 없다"가 아니라 "확인하지 못했다"이므로 화면이 구분해 보여 준다.
    임부금기(품목 단위)·건강 상태 금기(허가사항 본문)와 잔여 폴백은 성분코드 없이도 적용되므로 이 약에도 걸릴 수 있다."""

    drug_id: uuid.UUID
    drug_name: str


class QuickCheckResponse(BaseModel):
    total_drugs: int
    has_contraindication: bool
    risk_level: str  # safe / caution / critical
    contraindicated_count: int
    duplicate_effect_group_count: int = 0
    duplicate_ingredient_count: int = 0
    age_taboo_count: int = 0
    elderly_caution_count: int = 0
    pregnancy_taboo_count: int = 0
    dose_caution_count: int = 0
    condition_taboo_count: int = 0
    findings: list[QuickCheckFinding]
    condition_taboos: list[ConditionTaboo] = []
    age_cautions: list[AgeCaution] = []
    pregnancy_cautions: list[PregnancyCaution] = []
    dose_cautions: list[DoseCaution] = []
    unresolved_drugs: list[UnresolvedDrug] = []  # 요청한 약 중 성분코드가 없는 약(요청 순서)


class AnalysisGuideRequest(QuickCheckRequest):
    """quick_check와 동일한 drug_ids 검증(최소 1개, 최대 50개)을 그대로 재사용."""


class GuideSource(BaseModel):
    """AI 설명의 용어 풀이 근거 — 이 설명의 프롬프트에 실제로 들어간 풀이의 출처."""

    name: str
    url: str


class AnalysisGuideResponse(BaseModel):
    risk_level: str  # safe / caution / critical — quick_check가 확정한 값 그대로, AI가 바꾸지 않음
    guide_text: str
    is_ai_generated: bool = True
    # AI가 만든 설명일 때만 채워진다(정해진 문장·폴백 문구는 AI가 쓴 게 아니므로 비운다).
    model_name: str | None = None  # 설명을 만든 로컬 모델
    glossary_sources: list[GuideSource] = []  # 설명에 쓴 용어 풀이의 출처(없으면 빈 목록)
    disclaimer: str = (
        "이 설명은 AI가 생성한 참고용 안내이며 의학적 진단이 아닙니다. "
        "위급하거나 확신이 서지 않으면 반드시 의사·약사와 상담하세요."
    )
