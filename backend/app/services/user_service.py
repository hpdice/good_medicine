import uuid

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import get_encryptor
from app.core.exceptions import NotFoundError
from app.core.logging import logger
from app.core.security import hash_password
from app.models.analysis_result import AnalysisResult
from app.models.medicine_box import MedicineBoxEntry
from app.models.user import AuditLog, RefreshToken, User
from app.schemas.user import UserUpdate


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._enc = get_encryptor()

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundError("사용자를 찾을 수 없습니다.")
        return self._decrypt_user(user)

    async def update_user(self, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundError("사용자를 찾을 수 없습니다.")

        if data.name is not None:
            user.name = data.name
        if data.fcm_token is not None:
            user.fcm_token = data.fcm_token
        if data.health_conditions is not None:
            user.health_conditions_encrypted = self._enc.encrypt(data.health_conditions)
        if data.allergy_info is not None:
            user.allergy_info_encrypted = self._enc.encrypt(data.allergy_info)
        if "birth_year" in data.model_fields_set:  # 명시적 null이면 지운다(키를 안 보내면 그대로)
            user.birth_year_encrypted = (
                None if data.birth_year is None else self._enc.encrypt(data.birth_year)
            )
        if data.is_pregnant is not None:
            user.pregnancy_encrypted = self._enc.encrypt(data.is_pregnant)

        await self.db.commit()
        await self.db.refresh(user)
        return self._decrypt_user(user)

    async def delete_user(self, user_id: uuid.UUID) -> None:
        """개인정보보호법: 탈퇴 시 민감 정보 즉시 삭제 (이메일 재사용 가능하도록 tombstone 처리)

        사용자 행은 tombstone으로 남기므로(감사 로그 참조 보존) FK의 ON DELETE CASCADE가
        발동하지 않는다. 그래서 복약함·분석 이력(암호화된 건강·복약 정보)을 여기서 직접
        지우고, 남은 Refresh Token을 전부 폐기한다 — 그렇지 않으면 탈퇴 후에도 데이터가
        남고 옛 토큰으로 계속 접근할 수 있다.
        """
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundError("사용자를 찾을 수 없습니다.")

        await self.db.execute(delete(MedicineBoxEntry).where(MedicineBoxEntry.user_id == user_id))
        await self.db.execute(delete(AnalysisResult).where(AnalysisResult.user_id == user_id))
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked == False)  # noqa: E712
            .values(is_revoked=True)
        )
        self.db.add(AuditLog(user_id=user_id, action="delete_account"))

        user.health_conditions_encrypted = None
        user.allergy_info_encrypted = None
        user.birth_year_encrypted = None
        user.pregnancy_encrypted = None
        user.fcm_token = None
        user.email = f"deleted-{user.id}@deleted.local"
        user.hashed_password = hash_password(uuid.uuid4().hex)
        user.name = "탈퇴한 사용자"
        user.is_active = False
        await self.db.commit()

    def _decrypt_user(self, user: User) -> User:
        """복호화된 건강 정보를 user 객체에 임시 속성으로 추가.

        키 로테이션이나 데이터 손상으로 특정 필드 복호화가 실패해도 계정 전체가
        500이 되지 않도록 필드별로 격리해 None 처리한다.
        """
        user.__dict__["health_conditions"] = self._safe_decrypt(
            user.id, "health_conditions", user.health_conditions_encrypted
        )
        user.__dict__["allergy_info"] = self._safe_decrypt(
            user.id, "allergy_info", user.allergy_info_encrypted
        )
        user.__dict__["birth_year"] = self._safe_decrypt(
            user.id, "birth_year", user.birth_year_encrypted
        )
        user.__dict__["is_pregnant"] = self._safe_decrypt(
            user.id, "is_pregnant", user.pregnancy_encrypted
        )
        return user

    def _safe_decrypt(self, user_id: uuid.UUID, field_name: str, encrypted: str | None):
        if not encrypted:
            return None
        try:
            return self._enc.decrypt(encrypted)
        except Exception:
            logger.warning("복호화 실패: user_id=%s field=%s", user_id, field_name, exc_info=True)
            return None
