import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DurIngredientContraindication(Base):
    """성분 단위 DUR 병용금기 — 성분코드 쌍(정규 순서 a<b로 저장).

    `DURPrdlstInfoService03/getUsjntTabooInfoList03` 응답의
    `INGR_CODE` × `MIXTURE_INGR_CODE`를 품목쌍(797K건)에서 추출·중복제거한 것.
    품목 단위 `drug_interactions`와 달리 특정 품목쌍 열거 여부에 의존하지 않는다.
    """

    __tablename__ = "dur_ingredient_contraindications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    ingr_code_a: Mapped[str] = mapped_column(String(20), nullable=False)
    ingr_code_b: Mapped[str] = mapped_column(String(20), nullable=False)
    ingr_kor_a: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ingr_kor_b: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prohibit_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # prohibit_content에서 로컬 LLM이 1회 추출한 위험/증상 태그 (sync.py extract_risk_tags)
    risk_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 품목쌍에서 합성한 규칙 표식('derived-from-product …'); validate_db가 읽는다
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingr_code_a", "ingr_code_b", name="uq_dur_ingr_contra_pair"),
        Index("idx_dur_ingr_contra_a", "ingr_code_a"),
        Index("idx_dur_ingr_contra_b", "ingr_code_b"),
    )


class DurIngredientEffectGroup(Base):
    """성분 단위 DUR 효능군중복주의 — 같은 `dur_seq`에 속한 성분코드 멤버십.

    `DURPrdlstInfoService03/getEfcyDplctInfoList03` 응답의 `INGR_CODE` + `DUR_SEQ`.
    같은 `dur_seq`에 서로 다른 약품의 성분이 2개 이상 매핑되면 효능군중복주의 대상
    (병용금기와 달리 '주의' 등급).
    """

    __tablename__ = "dur_ingredient_effect_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    ingr_code: Mapped[str] = mapped_column(String(20), nullable=False)
    dur_seq: Mapped[str] = mapped_column(String(20), nullable=False)
    effect_name: Mapped[str] = mapped_column(String(200), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingr_code", "dur_seq", name="uq_dur_ingr_effect_ingr_dur_seq"),
        Index("idx_dur_ingr_effect_dur_seq", "dur_seq"),
        Index("idx_dur_ingr_effect_ingr_code", "ingr_code"),
    )
