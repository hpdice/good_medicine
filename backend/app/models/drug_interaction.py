import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DrugInteraction(Base):
    __tablename__ = "drug_interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    drug1_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drug2_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # contraindicated: 병용금기
    interaction_type: Mapped[str] = mapped_column(String(20), nullable=False)

    mechanism: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    drug1: Mapped["Drug"] = relationship(  # noqa: F821
        foreign_keys=[drug1_id], back_populates="interactions_as_drug1"
    )
    drug2: Mapped["Drug"] = relationship(  # noqa: F821
        foreign_keys=[drug2_id], back_populates="interactions_as_drug2"
    )

    __table_args__ = (
        Index("idx_drug_interactions_pair", "drug1_id", "drug2_id"),
    )
