import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, field_validator

from app.schemas.drug import DrugSearchResult

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_intake_times(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    for t in v:
        if not _HHMM_RE.match(t):
            raise ValueError(f"intake_times는 HH:MM(24시간제) 형식이어야 합니다: {t!r}")
    return v


class MedicineBoxAddManual(BaseModel):
    drug_id: uuid.UUID
    prescribed_date: date | None = None
    dosage_per_intake: str | None = None
    intake_frequency: str | None = None
    intake_duration_days: int | None = None
    intake_times: list[str] | None = None  # HH:MM, 매일 이 시각에 복약 알림
    reminder_enabled: bool = False
    notes: str | None = None

    _validate_intake_times = field_validator("intake_times")(_validate_intake_times)


class MedicineBoxUpdate(BaseModel):
    dosage_per_intake: str | None = None
    intake_frequency: str | None = None
    intake_duration_days: int | None = None
    intake_times: list[str] | None = None
    reminder_enabled: bool | None = None
    is_current: bool | None = None
    notes: str | None = None

    _validate_intake_times = field_validator("intake_times")(_validate_intake_times)


class MedicineBoxEntryResponse(BaseModel):
    id: uuid.UUID
    drug: DrugSearchResult
    prescribed_date: date | None
    dosage_per_intake: str | None
    intake_frequency: str | None
    intake_duration_days: int | None
    intake_times: list[str] | None = None
    reminder_enabled: bool = False
    is_current: bool
    added_method: str
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
