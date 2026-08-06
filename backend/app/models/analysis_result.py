import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisResult(Base):
    """AI가 생성한 대응 가이드(첨언) 이력. 위험도 판정(risk_level)은 이미
    AnalysisService.quick_check()가 규칙 기반으로 확정한 값을 스냅샷으로만
    저장한다 — 이 테이블/AI는 판정 자체에 관여하지 않는다.
    """

    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    drug_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    findings_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # AES-256-GCM 암호화 — 사용자의 건강정보/알레르기 정보가 프롬프트 컨텍스트로
    # 들어가 가이드 본문에 반영될 수 있어 다른 민감 필드와 동일하게 암호화한다.
    action_guide_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
