import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DurIngredientMaster(Base):
    """DUR 성분코드(D코드) ↔ 한글·영문 성분명 조회표.

    `DURIrdntInfoService03`(DUR 성분정보) 7개 오퍼레이션 응답의 `INGR_*`·`MIXTURE_INGR_*`를
    모아 중복을 뺀 것. 판정에는 쓰지 않고, 약 → 성분코드 해소(`drug_ingredients`, source='hira_eng')를 위한
    영문명 매칭의 기준이다. 같은 코드에 이름이 둘 이상 내려오면 덮어쓰지 않고 행을 나눠 둔다
    (코드·한글·영문 조합이 유일 키).
    """

    __tablename__ = "dur_ingredient_master"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    ingr_code: Mapped[str] = mapped_column(String(20), nullable=False)
    ingr_kor: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ingr_eng: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # 영문명 비교 키(helpers.norm_ingr_eng) — 심평원 영문 일반명과 완전 일치로 맞춘다
    ingr_eng_norm: Mapped[str | None] = mapped_column(String(300), nullable=True)
    mix_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # '단일' | '복합'

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "ingr_code", "ingr_kor", "ingr_eng",
            name="uq_dur_ingr_master_code_names", postgresql_nulls_not_distinct=True,
        ),
        Index("idx_dur_ingr_master_code", "ingr_code"),
        Index("idx_dur_ingr_master_eng_norm", "ingr_eng_norm"),
    )

