import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
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


class DurItemPregnancyTaboo(Base):
    """DUR 임부금기 — **품목(ITEM_SEQ) 단위**. 임신 중인 사용자의 복약함 약품에 적용.

    `DURPrdlstInfoService03/getPwnmTabooInfoList03` 응답을 그대로 품목 단위로 적재한다.
    다른 DUR 규칙과 달리 성분 단위로 합치지 않는 이유(2026-10-09 실측, 16,073행):
    - 응답이 "이 품목이 금기"라고 품목을 정확히 나열하고, 비고(`REMARK`)에 적용 범위가
      붙는다 — '경구'(661행), '외용 (모발용제)'(201), '겔제, 첩부제 포함'(187),
      '제2형 당뇨병'(25) 등. 같은 성분이라도 제형·적응증에 따라 금기 여부가 다르므로
      성분코드로 합치면 외용제까지 경고하는 오탐이 생긴다.
    - 성분코드 해소율(61.5%)에 의존하지 않는다 — 품목은 `drugs.item_seq`로 곧바로 닿는다.
    한 품목에 성분별 행이 여럿일 수 있어(복합제) (item_seq, ingr_code)를 유일 키로 둔다.
    `PROHBT_CONTENT`에는 '1등급/2등급' 같은 등급 표기와 근거(동물실험·기형 보고)가
    자유 텍스트로 섞여 있어 원문 그대로 보여준다.
    """

    __tablename__ = "dur_item_pregnancy_taboo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    item_seq: Mapped[str] = mapped_column(String(50), nullable=False)
    ingr_code: Mapped[str] = mapped_column(String(20), nullable=False)
    ingr_kor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prohibit_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("item_seq", "ingr_code", name="uq_dur_item_pregnancy_item_ingr"),
        Index("idx_dur_item_pregnancy_item_seq", "item_seq"),
    )


class DurIngredientAgeCaution(Base):
    """성분 단위 DUR 특정연령대금기·노인주의 — 성분코드 + 연령 규칙.

    `DURPrdlstInfoService03/getSpcifyAgrdeTabooInfoList03`(특정연령대금기)와
    `getOdsnAtentInfoList03`(노인주의) 응답의 `INGR_CODE`+`TYPE_NAME`+`PROHBT_CONTENT`.
    두 엔드포인트 다 `dur_seq` 같은 그룹핑 필드가 없고, `TYPE_NAME`이 이미
    "특정연령대금기"/"노인주의"로 구분돼 있어 하나의 테이블에 `rule_type`으로 합친다.

    **실측 확인(2026-09-12)**: 나이 기준을 담은 구조화 필드가 없다 — 유일한 단서인
    `PROHBT_CONTENT`(자유 텍스트)를 500건 샘플링한 결과 "OO세 미만" 같은 숫자 패턴은
    3.6%뿐이고, 대부분 "영아/소아/신생아" 같은 범주어이거나 나이 언급이 아예 없다.
    그래서 `age_threshold`/`age_unit`/`age_direction`은 정규식으로 뽑히면 채우고
    실패하면 전부 NULL로 남긴다 — quick_check는 이 세 필드가 모두 있을 때만 나이
    비교를 하고, NULL이면 판정에 관여시키지 않는다(원문은 표시용으로 남김).
    노인주의는 반대로 엔드포인트 자체가 이미 "노인 대상"이라는 뜻이라 이 필드들이
    필요 없다 — 성분코드 존재 여부 + 고정 기준(만 65세 이상)만으로 판정한다.
    """

    __tablename__ = "dur_ingredient_age_caution"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    ingr_code: Mapped[str] = mapped_column(String(20), nullable=False)
    ingr_kor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)  # age_taboo | elderly_caution
    prohibit_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PROHBT_CONTENT에서 정규식으로 뽑은 구조화 값 — 셋 다 있을 때만 quick_check가 사용
    age_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 세 | 개월
    age_direction: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 미만|이상|이하|초과

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingr_code", "rule_type", name="uq_dur_ingr_age_caution_code_type"),
        Index("idx_dur_ingr_age_caution_code", "ingr_code"),
    )
