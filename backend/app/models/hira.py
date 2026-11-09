import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HiraItemGenCode(Base):
    """심평원 약가마스터(의약품표준코드) — 품목기준코드 ↔ 일반명코드(주성분코드).

    원본은 포장 단위 행(약 31만)이라 (품목, 일반명코드)로 줄여 담는다. 품목기준코드는
    `drugs.item_seq`와 같은 체계다. 일반명코드 9자리 중 7번째 글자가 투여경로(A 내복·B 주사·C 외용·D 기타).
    `cancelled_on`: 그 (품목, 코드)의 포장이 모두 취소됐으면 가장 늦은 취소일, 하나라도 살아 있으면 NULL."""

    __tablename__ = "hira_item_gen_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    item_seq: Mapped[str] = mapped_column(String(20), nullable=False)
    gen_code: Mapped[str] = mapped_column(String(9), nullable=False)
    etc_otc: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 전문의약품 | 일반의약품 | 한약재 …
    atc_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cancelled_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("item_seq", "gen_code", name="uq_hira_item_gen_code"),
        Index("idx_hira_item_gen_code_gen", "gen_code"),
    )


class HiraGenCode(Base):
    """심평원 약가마스터(의약품주성분) — 일반명코드 하나에 한 번만 정해지는 속성(제형·투여경로·분류).

    원본 CSV는 성분 행마다 이 값을 되풀이해 적는다(복합제 7,783개 코드에서 값 충돌 0건 — 실측). 값이 성분이 아니라
    일반명코드에만 종속(2NF)이라 따로 뺀다. `route`는 투여경로 구분(내복 | 주사 | 외용 | 기타)에 쓴다."""

    __tablename__ = "hira_gen_codes"

    gen_code: Mapped[str] = mapped_column(String(9), primary_key=True)
    form_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    form_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    route: Mapped[str | None] = mapped_column(String(10), nullable=True)
    class_no: Mapped[str | None] = mapped_column(String(5), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HiraGenIngredient(Base):
    """심평원 약가마스터(의약품주성분) — 일반명코드의 성분 구성.

    복합제는 성분별로 행이 따로 있어 (일반명코드, 순번)으로 구분한다. `ingr_name`은 대부분 영문 일반명
    (97.2%, 예: 'amlodipine besylate (as amlodipine)')이라 DUR 성분정보의 영문명과 맞춰 성분코드를 찾는다.
    `strength`·`unit`은 용량 계산에 쓴다. 제형·투여경로는 일반명코드의 속성이라 `HiraGenCode`에 있다."""

    __tablename__ = "hira_gen_ingredients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    gen_code: Mapped[str] = mapped_column(
        String(9), ForeignKey("hira_gen_codes.gen_code", ondelete="CASCADE", name="fk_hira_gen_ingredients_gen_code"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 같은 일반명코드 안에서 원본 행 순서(1부터)
    ingr_name: Mapped[str] = mapped_column(String(300), nullable=False)
    strength: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 원문 그대로(예: '0.25')
    unit: Mapped[str | None] = mapped_column(String(60), nullable=True)  # 원문 그대로(예: 'mg', 'g(A액400ml중)')

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("gen_code", "seq", name="uq_hira_gen_ingredient_seq"),
    )
