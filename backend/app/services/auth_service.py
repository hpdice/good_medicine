import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ConflictError, TooManyRequestsError, UnauthorizedError
from app.core.login_guard import login_guard
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_token_expiry,
    hash_password,
    verify_password,
)
from app.models.user import AuditLog, RefreshToken, User
from app.schemas.user import UserLogin, UserRegister


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, req: UserRegister, ip: str, user_agent: str | None) -> User:
        if not req.privacy_consent or not req.health_data_consent:
            from app.core.exceptions import ValidationError
            raise ValidationError("개인정보 및 건강정보 수집 동의가 필요합니다.")

        existing = await self.db.scalar(select(User).where(User.email == req.email))
        if existing:
            raise ConflictError("이미 사용 중인 이메일입니다.")

        now = datetime.now(timezone.utc)
        user = User(
            email=req.email,
            hashed_password=hash_password(req.password),
            name=req.name,
            privacy_consent_at=now,
            health_data_consent_at=now,
        )
        self.db.add(user)
        await self.db.flush()

        self.db.add(AuditLog(
            user_id=user.id, action="register", ip_address=ip, user_agent=user_agent
        ))
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def login(self, req: UserLogin, ip: str, user_agent: str | None) -> dict:
        # 계정별 실패 제한 — 잠겨 있으면 맞는 비밀번호도 거부한다(핸들러 본문 전에 확인).
        retry_after = login_guard.retry_after(req.email)
        if retry_after:
            raise TooManyRequestsError(
                "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.", retry_after=retry_after
            )

        user = await self.db.scalar(select(User).where(User.email == req.email))
        if not user or not verify_password(req.password, user.hashed_password):
            login_guard.record_failure(req.email)
            raise UnauthorizedError("이메일 또는 비밀번호가 올바르지 않습니다.")
        if not user.is_active:
            raise UnauthorizedError("비활성화된 계정입니다.")
        login_guard.reset(req.email)

        access_token = create_access_token(str(user.id))
        refresh_token_str = create_refresh_token(str(user.id))

        token_hash = hashlib.sha256(refresh_token_str.encode()).hexdigest()
        self.db.add(RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=get_token_expiry(settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ))
        self.db.add(AuditLog(
            user_id=user.id, action="login", ip_address=ip, user_agent=user_agent
        ))
        await self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token_str,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def refresh(self, refresh_token_str: str) -> dict:
        from jose import JWTError

        from app.core.security import decode_token

        try:
            jwt_claims = decode_token(refresh_token_str)
            if jwt_claims.get("type") != "refresh":
                raise UnauthorizedError()
            user_id = uuid.UUID(jwt_claims["sub"])
        except (JWTError, ValueError, KeyError) as e:
            raise UnauthorizedError() from e

        token_hash = hashlib.sha256(refresh_token_str.encode()).hexdigest()
        token_record = await self.db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False,  # noqa: E712
            )
        )
        if not token_record:
            raise UnauthorizedError("만료되었거나 유효하지 않은 토큰입니다.")

        # 단일 사용: 즉시 폐기 후 새 토큰 발급
        token_record.is_revoked = True

        # 탈퇴(비활성) 계정은 갱신 불가 — 이 검사가 없으면 탈퇴 전에 받은 Refresh Token으로
        # 새 7일짜리 토큰을 계속 이어 받아 무기한 접근할 수 있다.
        is_active = await self.db.scalar(select(User.is_active).where(User.id == user_id))
        if not is_active:
            await self.db.commit()
            raise UnauthorizedError("비활성화된 계정입니다.")

        new_access = create_access_token(str(user_id))
        new_refresh = create_refresh_token(str(user_id))
        new_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
        self.db.add(RefreshToken(
            user_id=user_id,
            token_hash=new_hash,
            expires_at=get_token_expiry(settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ))
        await self.db.commit()

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def logout(self, refresh_token_str: str) -> None:
        token_hash = hashlib.sha256(refresh_token_str.encode()).hexdigest()
        record = await self.db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        if record:
            record.is_revoked = True
            await self.db.commit()
