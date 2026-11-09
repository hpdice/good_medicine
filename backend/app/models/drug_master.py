import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DrugMaster(Base):
    """약 하나당 한 줄로 모은 통합 데이터셋 — 이름·업체·분류·성분·함량·제형·정보 유무를 조인해 둔 결과.

    원천(식약처 e약은요·허가정보, 심평원 약가마스터, DUR 성분코드 연결)은 그대로 두고, `sync.py build_drugs_master`가
    **매번 전부 다시 만든다**(API 미사용). 판정 규칙(`dur_*`)과 `AnalysisService`는 이 테이블을 읽지 않는다 —
    성분 판정은 `drug_ingredients`가 그대로 맡고, 이 테이블은 "이 약에 대해 우리가 아는 것"을 한눈에 보이게 한다.

    `ingredient_status`: `dur_resolved`(DUR 성분코드가 맺혀 성분 단위 판정 가능) | `hira_only`(심평원 성분은 알지만
    DUR 코드가 없음 — 대부분 DUR에 그 성분의 규칙 자체가 없는 경우) | `none`(성분 정보가 전혀 없음)."""

    __tablename__ = "drugs_master"

    drug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drugs.id", ondelete="CASCADE"), primary_key=True
    )
    item_seq: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    # 식별·분류 (식약처 허가정보 + 심평원)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    simple_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    entp_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    etc_otc_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    class_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    atc_code: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # 성분 — 심평원 성분 구성(영문명·함량·제형·경로)과 DUR 성분코드 연결(한글명·코드·출처·1개당 mg)을 나란히
    hira_components: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    dur_ingredients: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    dur_ingr_codes: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, server_default="{}")
    dosage_form: Mapped[str | None] = mapped_column(Text, nullable=True)
    route: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 정제 상태 — "문제 없음"과 "판정할 데이터가 없음"을 구분하기 위한 값
    ingredient_status: Mapped[str] = mapped_column(String(20), nullable=False)
    judgeable: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # 설명 텍스트가 채워져 있는지(본문은 `drugs`에 있다)
    has_efficacy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_use_method: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_precautions: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_interaction_text: Mapped[bool] = mapped_column(Boolean, nullable=False)

    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_drugs_master_status", "ingredient_status"),
        Index("idx_drugs_master_dur_codes", "dur_ingr_codes", postgresql_using="gin"),
    )
