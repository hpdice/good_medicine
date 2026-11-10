import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.services.precautions import trim_precautions_for_display


def _trim_atpn(value: str | None) -> str | None:
    """화면에 내려 주는 주의사항에서 임상시험 결과 등을 뺀다(DB 원문·판정·AI 근거는 전문 그대로)."""
    return trim_precautions_for_display(value)


class DrugResponse(BaseModel):
    id: uuid.UUID
    item_seq: str
    item_name: str
    entp_name: str | None
    main_item_ingr: str | None
    ingr_name: list | None
    efcy_qesitm: str | None
    use_method_qesitm: str | None
    atpn_warn_qesitm: str | None
    atpn_qesitm: str | None
    intrc_qesitm: str | None
    se_qesitm: str | None
    class_name: str | None
    etc_otc_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

    _trim_atpn = field_validator("atpn_qesitm")(_trim_atpn)


class DrugSearchResult(BaseModel):
    id: uuid.UUID
    item_seq: str
    item_name: str
    simple_name: str | None
    entp_name: str | None
    class_name: str | None
    etc_otc_name: str | None
    efcy_qesitm: str | None
    use_method_qesitm: str | None
    atpn_warn_qesitm: str | None
    atpn_qesitm: str | None
    intrc_qesitm: str | None
    se_qesitm: str | None
    deposit_method_qesitm: str | None

    model_config = {"from_attributes": True}

    _trim_atpn = field_validator("atpn_qesitm")(_trim_atpn)


class DrugNameMatchRequest(BaseModel):
    names: list[str]


class OcrDose(BaseModel):
    """약봉투·처방전에서 읽은 복용 안내. 못 읽은 항목은 None — 앱이 복약함에 담을 때 미리 채운다."""

    units_per_intake: float | None = None  # 1회 투약량(정·캡슐 개수)
    times_per_day: int | None = None  # 1일 투여횟수
    duration_days: int | None = None  # 총 투약일수


class DrugNameMatchResult(BaseModel):
    queried_name: str
    matched: DrugSearchResult | None
    alternatives: list[DrugSearchResult]
    dose: OcrDose | None = None  # 사진 OCR 경로에서만 채운다

    model_config = {"from_attributes": True}


class OcrMatchResponse(BaseModel):
    """처방전/약봉투 사진 OCR 결과. 서버는 이미지를 저장하지 않으며,
    raw_text/candidates/matches 텍스트만 반환한다."""

    raw_text: str
    candidates: list[str]
    matches: list[DrugNameMatchResult]
