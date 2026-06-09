import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.drug import DrugSearchResult


class MedicineBoxAddManual(BaseModel):
    drug_id: uuid.UUID
    prescribed_date: date | None = None
    dosage_per_intake: str | None = None
    intake_frequency: str | None = None
    intake_duration_days: int | None = None
    notes: str | None = None


class MedicineBoxUpdate(BaseModel):
    dosage_per_intake: str | None = None
    intake_frequency: str | None = None
    intake_duration_days: int | None = None
    is_current: bool | None = None
    notes: str | None = None


class MedicineBoxEntryResponse(BaseModel):
    id: uuid.UUID
    drug: DrugSearchResult
    prescribed_date: date | None
    dosage_per_intake: str | None
    intake_frequency: str | None
    intake_duration_days: int | None
    is_current: bool
    added_method: str
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
