import uuid
from datetime import date, datetime

from pydantic import BaseModel


class DrugResponse(BaseModel):
    id: uuid.UUID
    item_seq: str
    item_name: str
    entp_name: str | None
    item_permit_date: date | None
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


class DrugNameMatchRequest(BaseModel):
    names: list[str]


class DrugNameMatchResult(BaseModel):
    queried_name: str
    matched: DrugSearchResult | None
    alternatives: list[DrugSearchResult]

    model_config = {"from_attributes": True}


class OcrMatchResponse(BaseModel):
    """처방전/약봉투 사진 OCR 결과. 서버는 이미지를 저장하지 않으며,
    raw_text/candidates/matches 텍스트만 반환한다."""

    raw_text: str
    candidates: list[str]
    matches: list[DrugNameMatchResult]
