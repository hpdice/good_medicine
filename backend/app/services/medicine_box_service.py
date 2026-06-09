import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.medicine_box import MedicineBoxEntry
from app.schemas.medicine_box import MedicineBoxAddManual, MedicineBoxUpdate


class MedicineBoxService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_entries(self, user_id: uuid.UUID, current_only: bool = True) -> list[MedicineBoxEntry]:
        stmt = (
            select(MedicineBoxEntry)
            .where(MedicineBoxEntry.user_id == user_id)
            .options(selectinload(MedicineBoxEntry.drug))
            .order_by(MedicineBoxEntry.created_at.desc())
        )
        if current_only:
            stmt = stmt.where(MedicineBoxEntry.is_current == True)  # noqa: E712
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def add_manual(self, user_id: uuid.UUID, data: MedicineBoxAddManual) -> MedicineBoxEntry:
        existing = await self.db.scalar(
            select(MedicineBoxEntry).where(
                MedicineBoxEntry.user_id == user_id,
                MedicineBoxEntry.drug_id == data.drug_id,
                MedicineBoxEntry.is_current == True,  # noqa: E712
            )
        )
        if existing:
            raise ConflictError("이미 복약 중인 약품입니다.")

        entry = MedicineBoxEntry(
            user_id=user_id,
            drug_id=data.drug_id,
            prescribed_date=data.prescribed_date,
            dosage_per_intake=data.dosage_per_intake,
            intake_frequency=data.intake_frequency,
            intake_duration_days=data.intake_duration_days,
            notes=data.notes,
            added_method="manual",
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        await self.db.refresh(entry, ["drug"])
        return entry

    async def update_entry(
        self, user_id: uuid.UUID, entry_id: uuid.UUID, data: MedicineBoxUpdate
    ) -> MedicineBoxEntry:
        entry = await self._get_entry_for_user(user_id, entry_id)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(entry, field, value)
        await self.db.commit()
        await self.db.refresh(entry, ["drug"])
        return entry

    async def delete_entry(self, user_id: uuid.UUID, entry_id: uuid.UUID) -> None:
        entry = await self._get_entry_for_user(user_id, entry_id)
        await self.db.delete(entry)
        await self.db.commit()

    async def _get_entry_for_user(self, user_id: uuid.UUID, entry_id: uuid.UUID) -> MedicineBoxEntry:
        entry = await self.db.get(MedicineBoxEntry, entry_id)
        if not entry:
            raise NotFoundError("항목을 찾을 수 없습니다.")
        if entry.user_id != user_id:
            raise ForbiddenError()
        return entry
