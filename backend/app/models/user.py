import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.medicine_box import MedicineBoxEntry


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 민감 건강정보: AES-256-GCM 암호화 후 저장
    health_conditions_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    allergy_info_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 출생연도(만 나이 계산용, DUR 특정연령대금기·노인주의 판정) — 계정 소유자 본인이 아니라
    # 보호자가 관리하는 대상(자녀·부모 등)의 나이일 수 있어 건강정보와 함께 암호화한다.
    birth_year_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 임신 여부(DUR 임부금기 판정용) — 출생연도와 같은 이유로 암호화. bool 하나를 암호화해 두는 건
    # '임신 중인지'가 그 자체로 민감한 건강정보이기 때문. NULL = 미입력(판정 스킵).
    pregnancy_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 개인정보보호법(PIPA) 동의 이력
    privacy_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_data_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # FCM 푸시 토큰 (사용자별 1개)
    fcm_token: Mapped[str | None] = mapped_column(String(512), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    medicine_box_entries: Mapped[list["MedicineBoxEntry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Refresh Token 단일 사용 보장을 위한 DB 저장"""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class AuditLog(Base):
    """감사 로그 - append-only, 삭제 불가"""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
