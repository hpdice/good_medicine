import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DrugEffectGroup(Base):
    """DUR 효능군중복주의 — 같은 효능군(DUR_SEQ)에 속한 약품 멤버십.

    병용금기(contraindicated)와 달리 절대 금기가 아닌 '주의' 등급이다.
    같은 dur_seq를 가진 약품 2개 이상을 함께 복용하면 효능 중복 주의 대상이다.
    """

    __tablename__ = "drug_effect_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    drug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dur_seq: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    effect_name: Mapped[str] = mapped_column(String(200), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("drug_id", "dur_seq", name="uq_drug_effect_groups_drug_dur_seq"),
        Index("idx_drug_effect_groups_dur_seq", "dur_seq"),
    )
