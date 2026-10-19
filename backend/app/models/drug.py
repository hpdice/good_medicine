import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Drug(Base):
    __tablename__ = "drugs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 정규화 매칭 키 (3개 소스 cross-source 통합용)
    drug_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # 식품의약품안전처 식별자
    item_seq: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    entp_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_permit_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 성분 정보
    main_item_ingr: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingr_name: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # 효능/용법/주의사항 (e약은요 데이터)
    efcy_qesitm: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_method_qesitm: Mapped[str | None] = mapped_column(Text, nullable=True)
    atpn_warn_qesitm: Mapped[str | None] = mapped_column(Text, nullable=True)
    atpn_qesitm: Mapped[str | None] = mapped_column(Text, nullable=True)
    intrc_qesitm: Mapped[str | None] = mapped_column(Text, nullable=True)
    se_qesitm: Mapped[str | None] = mapped_column(Text, nullable=True)
    deposit_method_qesitm: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 허가정보 상세 API(getDrugPrdtPrmsnDtlInq06)로 보강을 시도한 시각 — NULL이면 아직 안 해봄.
    # (성공했지만 값이 없는 약도 찍어 둬서 같은 약을 매번 다시 호출하지 않는다)
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 분류
    class_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    etc_otc_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 검색용 파생 컬럼 (item_name에서 괄호 제거)
    simple_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_drugs_item_name_trgm", "item_name", postgresql_using="gin",
              postgresql_ops={"item_name": "gin_trgm_ops"}),
        Index("idx_drugs_drug_key_trgm", "drug_key", postgresql_using="gin",
              postgresql_ops={"drug_key": "gin_trgm_ops"}),
        Index("idx_drugs_simple_name_trgm", "simple_name", postgresql_using="gin",
              postgresql_ops={"simple_name": "gin_trgm_ops"}),
    )
