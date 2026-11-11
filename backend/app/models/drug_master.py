from sqlalchemy import Boolean, Column, MetaData, String, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db.base import Base

# 뷰는 테이블이 아니라서 `Base.metadata`(create_all·TRUNCATE·autogenerate 대상)에 넣지 않는다 — 별도 MetaData에 둔다.
# 뷰 자체는 마이그레이션 0021이 만든다(테스트는 conftest 가 같은 정의를 만든다).
_view_metadata = MetaData()

_drugs_master = Table(
    "drugs_master",
    _view_metadata,
    Column("drug_id", UUID(as_uuid=True), primary_key=True),
    Column("item_seq", String(20)),
    Column("item_name", Text),
    Column("simple_name", Text),
    Column("entp_name", Text),
    Column("etc_otc_name", String(50)),
    Column("class_name", Text),
    Column("atc_code", String(10)),
    Column("hira_components", JSONB),
    Column("dur_ingredients", JSONB),
    Column("dur_ingr_codes", ARRAY(String(20))),
    Column("dosage_form", Text),
    Column("route", String(100)),
    Column("ingredient_status", String(20)),
    Column("judgeable", Boolean),
    Column("has_efficacy", Boolean),
    Column("has_use_method", Boolean),
    Column("has_precautions", Boolean),
    Column("has_interaction_text", Boolean),
)


class DrugMaster(Base):
    """약 하나당 한 줄로 모은 통합 데이터셋 — 이름·업체·분류·성분·함량·제형·정보 유무를 조인해 둔 **읽기 전용 뷰**.

    저장된 사본이 아니라 원천(`drugs`·`drug_ingredients`·`hira_*`)을 읽을 때마다 합친 결과라 원천과 항상 같고, 갱신 단계가 없다.
    판정(`AnalysisService`)은 정규화된 `drug_ingredients`를 직접 읽는다 — 같은 원천이라 결과가 같고 뷰를 거칠 이유가 없다.
    이 뷰는 한 행에 모아 봐야 하는 곳(성분 해소 상태 구분, 통계, 내보내기)이 읽는다.

    `ingredient_status`: `dur_resolved`(DUR 성분코드가 맺혀 성분 단위 판정 가능) | `hira_only`(심평원 성분은 알지만
    DUR 코드가 없음 — 대부분 DUR에 그 성분의 규칙 자체가 없는 경우) | `none`(성분 정보가 전혀 없음)."""

    __table__ = _drugs_master
