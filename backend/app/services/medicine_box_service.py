import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import get_encryptor
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import logger
from app.models.drug import Drug
from app.models.medicine_box import MedicineBoxEntry
from app.models.user import User
from app.schemas.drug import DrugSearchResult
from app.schemas.medicine_box import (
    MedicineBoxAddManual,
    MedicineBoxEntryResponse,
    MedicineBoxUpdate,
)
from app.services import fcm_service
from app.services.analysis_service import AnalysisService
from app.services.drug_detail_service import DrugDetailService
from app.services.drug_service import DrugService

# payload_encrypted 안에 들어가는(=암호화되는) 필드. 나머지(user_id/is_current/
# added_method/타임스탬프)는 평문 컬럼으로 남는다.
_PAYLOAD_FIELDS = {
    "drug_id",
    "prescribed_date",
    "dosage_per_intake",
    "intake_frequency",
    "intake_duration_days",
    "intake_times",
    "reminder_enabled",
    "notes",
}


class MedicineBoxService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._enc = get_encryptor()

    # ------------------------------------------------------------------ #
    # 내부: 암호화 payload 로드/조립                                        #
    # ------------------------------------------------------------------ #

    async def _load_with_payload(
        self, user_id: uuid.UUID, current_only: bool = True
    ) -> list[tuple[MedicineBoxEntry, dict]]:
        """사용자의 복약함 행 + 복호화된 payload dict 쌍을 최신순으로 반환."""
        stmt = (
            select(MedicineBoxEntry)
            .where(MedicineBoxEntry.user_id == user_id)
            .order_by(MedicineBoxEntry.created_at.desc())
        )
        if current_only:
            stmt = stmt.where(MedicineBoxEntry.is_current == True)  # noqa: E712
        result = await self.db.execute(stmt)
        entries = list(result.scalars().all())
        return [(e, self._enc.decrypt(e.payload_encrypted)) for e in entries]

    def _build_response(
        self, entry: MedicineBoxEntry, drug: Drug, payload: dict
    ) -> MedicineBoxEntryResponse:
        return MedicineBoxEntryResponse(
            id=entry.id,
            drug=DrugSearchResult.model_validate(drug),
            prescribed_date=payload.get("prescribed_date"),
            dosage_per_intake=payload.get("dosage_per_intake"),
            intake_frequency=payload.get("intake_frequency"),
            intake_duration_days=payload.get("intake_duration_days"),
            intake_times=payload.get("intake_times"),
            reminder_enabled=payload.get("reminder_enabled", False),
            is_current=entry.is_current,
            added_method=entry.added_method,
            notes=payload.get("notes"),
            created_at=entry.created_at,
        )

    # ------------------------------------------------------------------ #
    # 공개 API                                                            #
    # ------------------------------------------------------------------ #

    async def list_entries(
        self, user_id: uuid.UUID, current_only: bool = True
    ) -> list[MedicineBoxEntryResponse]:
        rows = await self._load_with_payload(user_id, current_only=current_only)
        drug_ids = [uuid.UUID(p["drug_id"]) for _, p in rows]
        drugs = await DrugService(self.db).get_drugs_by_ids(drug_ids) if drug_ids else {}

        out: list[MedicineBoxEntryResponse] = []
        for entry, payload in rows:
            drug = drugs.get(uuid.UUID(payload["drug_id"]))
            if drug is None:
                logger.warning(
                    "복약함 항목 %s 의 약품 %s 이(가) drugs 테이블에 없음 — 응답에서 제외",
                    entry.id, payload["drug_id"],
                )
                continue
            out.append(self._build_response(entry, drug, payload))
        return out

    async def add_manual(
        self, user_id: uuid.UUID, data: MedicineBoxAddManual
    ) -> MedicineBoxEntryResponse:
        drug = await self.db.get(Drug, data.drug_id)
        if drug is None:
            raise NotFoundError("약품을 찾을 수 없습니다.")

        rows = await self._load_with_payload(user_id, current_only=True)
        if any(p["drug_id"] == str(data.drug_id) for _, p in rows):
            raise ConflictError("이미 복약 중인 약품입니다.")

        # e약은요에 없는 약(대부분의 전문의약품)은 허가정보 상세로 효능·용법·주의·성분을 채운다.
        # 성분이 채워지면 아래 병용금기 푸시·이후 quick_check가 이 약을 성분 단위로 볼 수 있다.
        # 부가 기능이라 실패해도 약 추가는 계속한다.
        try:
            await DrugDetailService(self.db).ensure_detail(drug)
        except Exception:
            await self.db.rollback()
            logger.exception("허가정보 상세 보강 중 오류 (약품 추가는 계속 진행) drug_id=%s", data.drug_id)
            drug = await self.db.get(Drug, data.drug_id)
            if drug is None:
                raise NotFoundError("약품을 찾을 수 없습니다.")

        payload = data.model_dump(mode="json")  # date/UUID → 문자열
        entry = MedicineBoxEntry(
            user_id=user_id,
            payload_encrypted=self._enc.encrypt(payload),
            added_method="manual",
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)

        try:
            await self._notify_if_contraindicated(user_id, new_drug_id=data.drug_id)
        except Exception:
            # 푸시 발송은 부가 기능 — 실패해도 이미 커밋된 약품 추가 자체는 성공으로 유지한다.
            logger.exception("병용금기 푸시 알림 발송 중 오류 (약품 추가는 정상 처리됨)")
        return self._build_response(entry, drug, payload)

    async def update_entry(
        self, user_id: uuid.UUID, entry_id: uuid.UUID, data: MedicineBoxUpdate
    ) -> MedicineBoxEntryResponse:
        entry = await self._get_entry_for_user(user_id, entry_id)

        changes = data.model_dump(exclude_none=True, mode="json")
        if "is_current" in changes:
            entry.is_current = changes.pop("is_current")
        payload = self._enc.decrypt(entry.payload_encrypted)
        if changes:
            payload.update({k: v for k, v in changes.items() if k in _PAYLOAD_FIELDS})
            entry.payload_encrypted = self._enc.encrypt(payload)

        await self.db.commit()
        await self.db.refresh(entry)

        drug = await self.db.get(Drug, uuid.UUID(payload["drug_id"]))
        if drug is None:
            raise NotFoundError("약품을 찾을 수 없습니다.")
        return self._build_response(entry, drug, payload)

    async def delete_entry(self, user_id: uuid.UUID, entry_id: uuid.UUID) -> None:
        entry = await self._get_entry_for_user(user_id, entry_id)
        await self.db.delete(entry)
        await self.db.commit()

    # ------------------------------------------------------------------ #
    # 내부                                                                #
    # ------------------------------------------------------------------ #

    async def _notify_if_contraindicated(
        self, user_id: uuid.UUID, new_drug_id: uuid.UUID
    ) -> None:
        """새로 추가된 약품이 기존 복약 목록과 병용금기이면 FCM 푸시를 발송한다.

        OCR로 백그라운드에서 약을 추가하는 흐름에서는 사용자가 화면을 보고 있지
        않을 수 있어, 클라이언트 quick-check와 별개로 서버에서도 즉시 알린다.

        푸시는 Google FCM(해외)을 거치므로 약 이름·ID를 싣지 않는다 — "누가 무슨 약을
        먹는지"는 국내 서버 밖으로 내보내지 않는다.
        """
        if not fcm_service.is_configured():
            return

        user = await self.db.get(User, user_id)
        if not user or not user.fcm_token:
            return

        rows = await self._load_with_payload(user_id, current_only=True)
        box_drug_ids = [uuid.UUID(p["drug_id"]) for _, p in rows]
        if len(box_drug_ids) < 2:
            return

        # quick_check와 동일한 판정(성분 경로 + 잔여 폴백)을 재사용한다.
        check = await AnalysisService(self.db).quick_check(box_drug_ids)
        if not any(
            f.interaction_type == "contraindicated" and new_drug_id in (f.drug1_id, f.drug2_id)
            for f in check.findings
        ):
            return

        result = await fcm_service.send_push(
            token=user.fcm_token,
            title="복약함을 확인해 주세요",
            body="함께 먹으면 안 되는 약이 복약함에 있어요. 앱에서 확인하세요.",
            data={"type": "contraindication"},
        )
        if result is False:
            user.fcm_token = None
            await self.db.commit()

    async def _get_entry_for_user(
        self, user_id: uuid.UUID, entry_id: uuid.UUID
    ) -> MedicineBoxEntry:
        entry = await self.db.get(MedicineBoxEntry, entry_id)
        if not entry:
            raise NotFoundError("항목을 찾을 수 없습니다.")
        if entry.user_id != user_id:
            raise ForbiddenError()
        return entry
