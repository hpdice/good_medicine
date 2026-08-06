import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import get_encryptor
from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserUpdate

logger = logging.getLogger(__name__)


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
            raise NotFoundError()

        if data.name is not None:
            user.name = data.name
        if data.phone_number is not None:
            user.phone_number = data.phone_number
        if data.fcm_token is not None:
            user.fcm_token = data.fcm_token
        if data.health_conditions is not None:
            user.health_conditions_encrypted = self._enc.encrypt(data.health_conditions)
        if data.allergy_info is not None:
            user.allergy_info_encrypted = self._enc.encrypt(data.allergy_info)

        await self.db.commit()
        await self.db.refresh(user)
        return self._decrypt_user(user)

    async def delete_user(self, user_id: uuid.UUID) -> None:
        """개인정보보호법: 탈퇴 시 민감 정보 즉시 삭제 (이메일 재사용 가능하도록 tombstone 처리)"""
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundError()

        user.health_conditions_encrypted = None
        user.allergy_info_encrypted = None
        user.fcm_token = None
        user.email = f"deleted-{user.id}@deleted.local"
        user.hashed_password = hash_password(uuid.uuid4().hex)
        user.name = "탈퇴한 사용자"
        user.phone_number = None
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
        return user

    def _safe_decrypt(self, user_id: uuid.UUID, field_name: str, encrypted: str | None):
        if not encrypted:
            return None
        try:
            return self._enc.decrypt(encrypted)
        except Exception:
            logger.warning("복호화 실패: user_id=%s field=%s", user_id, field_name, exc_info=True)
            return None
