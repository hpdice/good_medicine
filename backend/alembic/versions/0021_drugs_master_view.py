"""drugs_master — 저장된 사본(테이블)을 원천에서 바로 합치는 뷰로 바꾼다

원천(`drugs`·`drug_ingredients`·`hira_*`)이 유일한 저장소가 되고, 약 1행으로 모은 `drugs_master`는 그 위의 뷰다.
사본이 없으니 `build_drugs_master`·`refresh_drugs_master_row` 같은 갱신 단계와 낡을 위험이 사라진다.
요청 경로에서 이 테이블을 읽는 곳은 없었고(판정은 `drug_ingredients` 직접), 쓰기 쪽만 있었다.

뷰의 값은 테이블 때 구축 SQL과 같다 — 2026-11-10 운영 DB에서 임시 뷰와 테이블을 EXCEPT 로 비교해 다른 행 0개를 확인했다.
`built_at` 컬럼과 `dur_ingr_codes` GIN 인덱스는 없다(코드로 약을 찾을 땐 `drug_ingredients.ingr_code` 인덱스를 쓴다).

downgrade 는 뷰의 현재 값을 테이블로 옮겨 되돌린다(데이터 손실 없음).

Revision ID: 0021_drugs_master_view
Revises: 0020_hira_gen_codes
Create Date: 2026-11-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0021_drugs_master_view"
down_revision: Union[str, None] = "0020_hira_gen_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 뷰 정의 — 테스트(conftest)가 이 문자열을 그대로 불러 쓴다. 뷰를 바꿀 땐 새 마이그레이션에서 CREATE OR REPLACE 하고
# conftest 가 부르는 상수도 함께 바꾼다.
DRUGS_MASTER_VIEW_SQL = """
CREATE VIEW drugs_master AS
SELECT
    b.id AS drug_id, b.item_seq, b.item_name, b.simple_name, b.entp_name, b.etc_otc_name, b.class_name, b.atc_code,
    b.hira_components, b.dur_ingredients, b.dur_ingr_codes, b.dosage_form, b.route,
    CASE WHEN cardinality(b.dur_ingr_codes) > 0 THEN 'dur_resolved'
         WHEN jsonb_array_length(b.hira_components) > 0 THEN 'hira_only'
         ELSE 'none' END AS ingredient_status,
    cardinality(b.dur_ingr_codes) > 0 AS judgeable,
    b.has_efficacy, b.has_use_method, b.has_precautions, b.has_interaction_text
FROM (
    SELECT
        d.id, d.item_seq, d.item_name, d.simple_name, d.entp_name, d.etc_otc_name, d.class_name,
        (SELECT min(h.atc_code) FROM hira_item_gen_codes h
          WHERE h.item_seq = d.item_seq AND h.cancelled_on IS NULL) AS atc_code,
        COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'gen_code', g.gen_code, 'eng', g.ingr_name, 'strength', g.strength, 'unit', g.unit,
                       'form', c.form_name, 'route', c.route) ORDER BY g.gen_code, g.seq)
              FROM hira_item_gen_codes h JOIN hira_gen_ingredients g ON g.gen_code = h.gen_code
              JOIN hira_gen_codes c ON c.gen_code = g.gen_code
             WHERE h.item_seq = d.item_seq AND h.cancelled_on IS NULL
        ), '[]'::jsonb) AS hira_components,
        COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'code', di.ingr_code, 'kor', di.ingr_kor, 'source', di.source, 'amount_mg', di.amount_mg)
                       ORDER BY di.ingr_code)
              FROM drug_ingredients di WHERE di.drug_id = d.id AND di.ingr_code IS NOT NULL
        ), '[]'::jsonb) AS dur_ingredients,
        COALESCE(ARRAY(
            SELECT DISTINCT di.ingr_code FROM drug_ingredients di
             WHERE di.drug_id = d.id AND di.ingr_code IS NOT NULL ORDER BY 1
        ), '{}'::varchar[]) AS dur_ingr_codes,
        (SELECT string_agg(DISTINCT c.form_name, ', ') FROM hira_item_gen_codes h
           JOIN hira_gen_codes c ON c.gen_code = h.gen_code
          WHERE h.item_seq = d.item_seq AND h.cancelled_on IS NULL AND c.form_name IS NOT NULL) AS dosage_form,
        (SELECT string_agg(DISTINCT c.route, ', ') FROM hira_item_gen_codes h
           JOIN hira_gen_codes c ON c.gen_code = h.gen_code
          WHERE h.item_seq = d.item_seq AND h.cancelled_on IS NULL AND c.route IS NOT NULL) AS route,
        COALESCE(d.efcy_qesitm, '') <> '' AS has_efficacy,
        COALESCE(d.use_method_qesitm, '') <> '' AS has_use_method,
        COALESCE(d.atpn_qesitm, '') <> '' AS has_precautions,
        COALESCE(d.intrc_qesitm, '') <> '' AS has_interaction_text
    FROM drugs d
) b
"""


def upgrade() -> None:
    op.drop_table("drugs_master")  # 인덱스도 함께 사라진다
    op.execute(DRUGS_MASTER_VIEW_SQL)
    op.execute(
        "COMMENT ON VIEW drugs_master IS "
        "'약 1행으로 모은 통합 데이터셋 — drugs + 심평원 + DUR 성분 연결을 원천에서 바로 합친다(저장된 사본 없음)'"
    )


def downgrade() -> None:
    # 뷰를 지우면 값도 사라지므로 먼저 현재 값을 옮겨 둔다.
    op.execute("CREATE TABLE _drugs_master_snapshot AS SELECT * FROM drugs_master")
    op.execute("DROP VIEW drugs_master")
    op.create_table(
        "drugs_master",
        sa.Column("drug_id", sa.UUID(), nullable=False),
        sa.Column("item_seq", sa.String(length=20), nullable=False),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("simple_name", sa.Text(), nullable=True),
        sa.Column("entp_name", sa.Text(), nullable=True),
        sa.Column("etc_otc_name", sa.String(length=50), nullable=True),
        sa.Column("class_name", sa.Text(), nullable=True),
        sa.Column("atc_code", sa.String(length=10), nullable=True),
        sa.Column("hira_components", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("dur_ingredients", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("dur_ingr_codes", postgresql.ARRAY(sa.String(length=20)), server_default="{}", nullable=False),
        sa.Column("dosage_form", sa.Text(), nullable=True),
        sa.Column("route", sa.String(length=100), nullable=True),
        sa.Column("ingredient_status", sa.String(length=20), nullable=False),
        sa.Column("judgeable", sa.Boolean(), nullable=False),
        sa.Column("has_efficacy", sa.Boolean(), nullable=False),
        sa.Column("has_use_method", sa.Boolean(), nullable=False),
        sa.Column("has_precautions", sa.Boolean(), nullable=False),
        sa.Column("has_interaction_text", sa.Boolean(), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["drug_id"], ["drugs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("drug_id"),
        sa.UniqueConstraint("item_seq"),
    )
    op.execute(
        "INSERT INTO drugs_master (drug_id, item_seq, item_name, simple_name, entp_name, etc_otc_name, class_name, "
        "atc_code, hira_components, dur_ingredients, dur_ingr_codes, dosage_form, route, ingredient_status, "
        "judgeable, has_efficacy, has_use_method, has_precautions, has_interaction_text) "
        "SELECT drug_id, item_seq, item_name, simple_name, entp_name, etc_otc_name, class_name, atc_code, "
        "hira_components, dur_ingredients, dur_ingr_codes, dosage_form, route, ingredient_status, judgeable, "
        "has_efficacy, has_use_method, has_precautions, has_interaction_text FROM _drugs_master_snapshot"
    )
    op.execute("DROP TABLE _drugs_master_snapshot")
    op.create_index("idx_drugs_master_status", "drugs_master", ["ingredient_status"], unique=False)
    op.create_index(
        "idx_drugs_master_dur_codes", "drugs_master", ["dur_ingr_codes"], unique=False, postgresql_using="gin"
    )
