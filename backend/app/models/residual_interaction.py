import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResidualInteraction(Base):
    """성분 경로가 재현하지 못하는 품목쌍만 남긴 소형 폴백 테이블.

    성분 단위 판정이 품목쌍 단위 판정의 탐지를 100.0% 재현하므로 품목쌍 테이블은 두지 않는다.
    성분코드가 해소되지 않은 약(주로 외용제·희귀 품목)이 낀 ~217쌍만 여기 남긴다.

    `quick_check`는 선택 약 중 성분코드 미해소가 하나라도 있을 때만 이 테이블을 본다.
    """

    __tablename__ = "residual_interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    drug1_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drug2_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # contraindicated | duplicate_effect_group
    interaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mechanism: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_residual_interactions_pair", "drug1_id", "drug2_id"),
    )
