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
    # 'product'(DUR 품목정보 sweep에서 추출) | 'ingredient'(DUR 성분정보 API)
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="product")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingr_code_a", "ingr_code_b", name="uq_dur_ingr_contra_pair"),
        Index("idx_dur_ingr_contra_a", "ingr_code_a"),
        Index("idx_dur_ingr_contra_b", "ingr_code_b"),
    )


class DurIngredientEffectGroup(Base):
    """성분 단위 DUR 효능군중복주의 — 성분코드의 효능군·계열 멤버십.

    DUR 품목정보(`getEfcyDplctInfoList03`)·성분정보(`getEfcyDplctInfoList02`) 응답의
    `INGR_CODE` + `DUR_SEQ` + `EFFECT_NAME`(성분정보는 `EFFECT_CODE`) + `SERS_NAME`.
    `dur_seq`는 성분마다 따로 붙는 행 번호라 묶음 키가 아니다. 같은 **효능군 + 계열**
    (예: 혈압강하작용의약품 / ARB)에 서로 다른 약품의 성분이 2개 이상이면 효능군중복주의 대상
    (식약처 정의: "약리기전이 동일하거나 유사한 효능군 내에서 중복 투여", 병용금기와 달리 '주의' 등급).
    """

    __tablename__ = "dur_ingredient_effect_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    ingr_code: Mapped[str] = mapped_column(String(20), nullable=False)
    dur_seq: Mapped[str] = mapped_column(String(20), nullable=False)
    effect_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 계열(SERS_NAME, 예: 'ARB', '비스테로이드성 소염제') — 판정은 효능군 + 계열 단위
    sers_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="product")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingr_code", "dur_seq", name="uq_dur_ingr_effect_ingr_dur_seq"),
        Index("idx_dur_ingr_effect_dur_seq", "dur_seq"),
        Index("idx_dur_ingr_effect_ingr_code", "ingr_code"),
    )


class DurItemPregnancyTaboo(Base):
    """DUR 임부금기 — **품목(ITEM_SEQ) 단위**. 임신 중인 사용자의 복약함 약품에 적용.

    `DURPrdlstInfoService03/getPwnmTabooInfoList03` 응답을 그대로 품목 단위로 적재한다.
    다른 DUR 규칙과 달리 성분 단위로 합치지 않는 이유(16,073행):
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

    **나이 기준**: 품목정보 응답에는 구조화 필드가 없어 `PROHBT_CONTENT`(자유 텍스트)에서
    "OO세 미만"을 정규식으로 뽑는다(500건 중 3.6%만 성공). DUR 성분정보 응답에는 `AGE_BASE`
    ("18세 미만", "4주 미만")가 있어 이것으로 채운다 — 단, 같은 성분이 제형마다 기준이 다르면
    (예: 디클로페낙 주사제 '4주 미만', 정제 '18세 미만') 약의 제형을 모르므로 채우지 않는다.
    quick_check는 `age_threshold`/`age_unit`/`age_direction`이 모두 있을 때만 나이 비교를 하고,
    NULL이면 판정에 관여시키지 않는다(원문은 표시용으로 남김).
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
    age_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 세 | 개월 | 주
    age_direction: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 미만|이상|이하|초과
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="product")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingr_code", "rule_type", name="uq_dur_ingr_age_caution_code_type"),
        Index("idx_dur_ingr_age_caution_code", "ingr_code"),
    )


class DurIngredientDoseCaution(Base):
    """성분 단위 DUR 용량주의 — 하루 최대 투여량.

    DUR 성분정보 `getCpctyAtentInfoList02` 행 그대로(매 동기화마다 다시 만든다). `mix_codes`가 비어 있으면
    단일제 규칙(그 성분을 여러 약에서 먹어도 합친 하루 양의 상한, 예: 아세트아미노펜 4,000mg), 있으면 그 조성의
    복합제 한 품목에만 해당하는 규칙이다(예: 아세트아미노펜+트라마돌 복합제는 아세트아미노펜 2,600mg).
    `limits_mg`는 `MAX_QTY`에서 읽은 {성분코드: 하루 최대 mg} — '주1회'·'(고령자)'처럼 조건이 붙은 기준은
    읽지 않고(NULL) 판정에 쓰지 않는다. 제형(`form_name`)마다 기준이 다를 수 있어 quick_check가 제형을 거른다.
    """

    __tablename__ = "dur_ingredient_dose_caution"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    ingr_code: Mapped[str] = mapped_column(String(20), nullable=False)
    ingr_kor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 복합제 규칙의 나머지 성분코드(정렬, 쉼표 구분). 단일제 규칙은 ''
    mix_codes: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    form_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")  # '' = 모든 제형
    max_qty: Mapped[str] = mapped_column(String(300), nullable=False)  # 원문, 예: '아세트아미노펜 4,000밀리그램'
    limits_mg: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    prohibit_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("ingr_code", "mix_codes", "form_name", "max_qty", name="uq_dur_ingr_dose_caution_rule"),
        Index("idx_dur_ingr_dose_caution_code", "ingr_code"),
    )
