import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DrugIngredient(Base):
    """약품↔DUR 성분코드 정규화 링크.

    `drugs.ingr_name` JSONB는 표시용으로 계속 유지하고, 이 테이블은 성분 단위
    DUR 판정(`quick_check`)의 조인 대상이다. `ingr_code`는 식약처 DUR 성분코드
    (예: "D000762")로, `DURPrdlstInfoService03` 응답의 `INGR_CODE`/`MIXTURE_INGR_CODE`
    에서 채운다.

    source:
      - `dur`: DUR 병용금기/효능군중복 sweep 응답에서 직접 캡처 (신뢰도 높음)
      - `jsonb_fallback`: `ingr_name` JSONB 이름을 정규화해 이름→코드 사전으로 매칭
      - `permit_detail`: 허가정보 상세 API(복약함에 담을 때)의 성분명으로 매칭
      - `hira_eng`: 심평원 약가마스터 일반명(영문) ↔ DUR 성분정보 영문명 완전 일치
    """

    __tablename__ = "drug_ingredients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    drug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingr_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ingr_kor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="dur")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("drug_id", "ingr_code", name="uq_drug_ingredients_drug_ingr_code"),
        Index("idx_drug_ingredients_ingr_code", "ingr_code"),
    )
