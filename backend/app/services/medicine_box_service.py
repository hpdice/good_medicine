import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import logger
from app.models.medicine_box import MedicineBoxEntry
from app.models.user import User
from app.schemas.medicine_box import MedicineBoxAddManual, MedicineBoxUpdate
from app.services import fcm_service
from app.services.analysis_service import AnalysisService
from app.services.drug_service import DrugService


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

        try:
            await self._notify_if_contraindicated(user_id, entry)
        except Exception:
            # 푸시 발송은 부가 기능 — 실패해도 이미 커밋된 약품 추가 자체는 성공으로 유지한다.
            logger.exception("병용금기 푸시 알림 발송 중 오류 (약품 추가는 정상 처리됨)")
        return entry

    async def _notify_if_contraindicated(self, user_id: uuid.UUID, new_entry: MedicineBoxEntry) -> None:
        """새로 추가된 약품이 기존 복약 목록과 병용금기이면 FCM 푸시를 발송한다.

        OCR로 백그라운드에서 약을 추가하는 흐름에서는 사용자가 화면을 보고 있지
        않을 수 있어, 클라이언트 quick-check와 별개로 서버에서도 즉시 알린다.
        """
        if not fcm_service.is_configured():
            return

        user = await self.db.get(User, user_id)
        if not user or not user.fcm_token:
            return

        current_entries = await self.list_entries(user_id, current_only=True)
        box_drug_ids = [e.drug_id for e in current_entries]
        if len(box_drug_ids) < 2:
            return

        # quick_check와 동일한 판정(성분 경로 + 잔여 폴백)을 재사용한다.
        check = await AnalysisService(self.db).quick_check(box_drug_ids)
        contraindicated = [
            f
            for f in check.findings
            if f.interaction_type == "contraindicated"
            and new_entry.drug_id in (f.drug1_id, f.drug2_id)
        ]
        if not contraindicated:
            return

        other_id = next(
            d
            for d in (contraindicated[0].drug1_id, contraindicated[0].drug2_id)
            if d != new_entry.drug_id
        )
        drug_svc = DrugService(self.db)
        drugs = await drug_svc.get_drugs_by_ids([new_entry.drug_id, other_id])
        new_drug = drugs.get(new_entry.drug_id)
        other_drug = drugs.get(other_id)
        if not new_drug or not other_drug:
            return

        result = await fcm_service.send_push(
            token=user.fcm_token,
            title="병용금기 약물이 감지되었습니다",
            body=(
                f"{new_drug.simple_name or new_drug.item_name} · "
                f"{other_drug.simple_name or other_drug.item_name} 병용금기 — 앱에서 확인하세요."
            ),
            data={
                "type": "contraindication",
                "drug1_id": str(new_entry.drug_id),
                "drug2_id": str(other_id),
            },
        )
        if result is False:
            user.fcm_token = None
            await self.db.commit()

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
