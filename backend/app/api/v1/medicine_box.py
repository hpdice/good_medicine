import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user_id
from app.schemas.medicine_box import (
    MedicineBoxAddManual,
    MedicineBoxEntryResponse,
    MedicineBoxUpdate,
)
from app.services.medicine_box_service import MedicineBoxService

router = APIRouter()


@router.get("", response_model=list[MedicineBoxEntryResponse])
async def list_medicine_box(
    current_only: bool = True,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await MedicineBoxService(db).list_entries(user_id, current_only=current_only)


@router.post("", response_model=MedicineBoxEntryResponse, status_code=201)
async def add_drug_manual(
    body: MedicineBoxAddManual,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await MedicineBoxService(db).add_manual(user_id, body)


@router.patch("/{entry_id}", response_model=MedicineBoxEntryResponse)
async def update_entry(
    entry_id: uuid.UUID,
    body: MedicineBoxUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await MedicineBoxService(db).update_entry(user_id, entry_id, body)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await MedicineBoxService(db).delete_entry(user_id, entry_id)
