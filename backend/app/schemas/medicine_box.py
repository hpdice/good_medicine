import re
import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.schemas.drug import DrugSearchResult

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_intake_times(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    for t in v:
        if not _HHMM_RE.match(t):
            raise ValueError(f"intake_times는 HH:MM(24시간제) 형식이어야 합니다: {t!r}")
    return v


# 용량주의 판정용 복용량 — 1회에 먹는 정·캡슐 개수(반 알은 0.5)와 하루 복용 횟수. 약봉투의 '1회 투약량'·'1일 투여횟수'.
UnitsPerIntake = Annotated[float, Field(gt=0, le=20)]
TimesPerDay = Annotated[int, Field(ge=1, le=12)]


class MedicineBoxAddManual(BaseModel):
    drug_id: uuid.UUID
    prescribed_date: date | None = None
    intake_duration_days: int | None = None
    units_per_intake: UnitsPerIntake | None = None
    times_per_day: TimesPerDay | None = None
    intake_times: list[str] | None = None  # HH:MM, 매일 이 시각에 복약 알림
    reminder_enabled: bool = False
    notes: str | None = None

    _validate_intake_times = field_validator("intake_times")(_validate_intake_times)


class MedicineBoxUpdate(BaseModel):
    intake_duration_days: int | None = None
    # 복용량은 null을 보내면 지운다(다른 필드는 null = 변경 없음)
    units_per_intake: UnitsPerIntake | None = None
    times_per_day: TimesPerDay | None = None
    intake_times: list[str] | None = None
    reminder_enabled: bool | None = None
    is_current: bool | None = None
    notes: str | None = None

    _validate_intake_times = field_validator("intake_times")(_validate_intake_times)


class MedicineBoxEntryResponse(BaseModel):
    id: uuid.UUID
    drug: DrugSearchResult
    prescribed_date: date | None
    intake_duration_days: int | None
    units_per_intake: float | None = None
    times_per_day: int | None = None
    intake_times: list[str] | None = None
    reminder_enabled: bool = False
    is_current: bool
    added_method: str
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
