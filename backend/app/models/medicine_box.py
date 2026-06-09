import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MedicineBoxEntry(Base):
    __tablename__ = "medicine_box_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 처방 정보
    prescribed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dosage_per_intake: Mapped[str | None] = mapped_column(String(50), nullable=True)
    intake_frequency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intake_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 상태
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ocr_prescription, ocr_bag, manual
    added_method: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="medicine_box_entries")  # noqa: F821
    drug: Mapped["Drug"] = relationship()  # noqa: F821

    __table_args__ = (
        Index("idx_medicine_box_user_current", "user_id", "is_current"),
    )
