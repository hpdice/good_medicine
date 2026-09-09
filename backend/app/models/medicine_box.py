import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MedicineBoxEntry(Base):
    """사용자 복약함 항목.

    처방 상세(어떤 약인지 `drug_id` 포함, 용량·주기·메모)는 개인 건강정보이므로
    개별 컬럼이 아니라 단일 `payload_encrypted`(AES-256-GCM) 블롭에 담는다 —
    DB/디스크가 유출돼도 "누가 무슨 약을 먹는지"가 평문으로 드러나지 않게 한다.
    `MedicineBoxService`가 쓰기 시 암호화, 읽기 시 복호화한다.

    평문으로 남는 건 판정·인덱싱에 필요하고 민감도가 낮은 것뿐이다:
    `user_id`(소유자), `is_current`(활성 여부), `added_method`(입력 경로), 타임스탬프.
    `drug_id`가 암호화되면서 `drugs` FK/CASCADE는 사라진다 — 공공데이터라 사실상
    append-only이고, 서비스가 조회 시 존재하지 않는 약이면 그 항목을 건너뛴다.
    """

    __tablename__ = "medicine_box_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # {drug_id, prescribed_date, dosage_per_intake, intake_frequency,
    #  intake_duration_days, notes} 를 JSON 직렬화 후 AES-256-GCM 암호화한 base64 문자열
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # 상태 (판정/필터에 필요 — 평문 유지)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # ocr_prescription, ocr_bag, manual
    added_method: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="medicine_box_entries")  # noqa: F821

    __table_args__ = (
        Index("idx_medicine_box_user_current", "user_id", "is_current"),
    )
