"""품목 폴백 축소 — drug_interactions(227MB) + drug_effect_groups 폐기, residual_interactions로 교체

Revision ID: 0006_residual_interactions
Revises: 0005_dur_ingredient_tables
Create Date: 2026-09-01

성분 단위 판정이 품목 경로 탐지의 100.0%를 재현함이 확인되어, 성분코드 미해소 약이 낀
잔여 쌍만 residual_interactions에 옮기고 대형 두 테이블을 드롭한다.

이 마이그레이션의 INSERT는 구 품목 테이블이 채워진 상태에서만 동작한다. DB를 완전
초기화(`docker compose down -v`)한 뒤 처음부터 재구축하면 구 테이블이 빈 채로 드롭돼
residual_interactions가 비게 되므로, 그때는 `sync.py build_residual`로
`backend/seed/residual_interactions.json`(item_seq 쌍)에서 복원한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_residual_interactions"
down_revision: Union[str, None] = "0005_dur_ingredient_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "residual_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("drug1_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drug2_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interaction_type", sa.String(30), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_residual_interactions_drug1_id", "residual_interactions", ["drug1_id"])
    op.create_index("ix_residual_interactions_drug2_id", "residual_interactions", ["drug2_id"])
    op.create_index("idx_residual_interactions_pair", "residual_interactions",
                    ["drug1_id", "drug2_id"])

    # --- 병용금기: 성분 경로가 재현 못 하는 품목쌍만 이관 ---
    op.execute("""
        INSERT INTO residual_interactions (drug1_id, drug2_id, interaction_type, mechanism)
        SELECT t.d1, t.d2, 'contraindicated', t.mechanism
        FROM (
            SELECT DISTINCT ON (p.d1, p.d2) p.d1, p.d2, di.mechanism
            FROM (
                SELECT DISTINCT least(drug1_id, drug2_id) AS d1, greatest(drug1_id, drug2_id) AS d2
                FROM drug_interactions WHERE interaction_type = 'contraindicated'
            ) p
            JOIN drug_interactions di
              ON least(di.drug1_id, di.drug2_id) = p.d1
             AND greatest(di.drug1_id, di.drug2_id) = p.d2
             AND di.interaction_type = 'contraindicated'
            WHERE NOT EXISTS (
                SELECT 1
                FROM drug_ingredients a
                JOIN drug_ingredients b ON b.drug_id = p.d2
                JOIN dur_ingredient_contraindications c
                  ON (c.ingr_code_a = a.ingr_code AND c.ingr_code_b = b.ingr_code)
                  OR (c.ingr_code_a = b.ingr_code AND c.ingr_code_b = a.ingr_code)
                WHERE a.drug_id = p.d1
            )
        ) t
    """)

    # --- 효능군중복: 성분 경로가 재현 못 하는 품목쌍만 이관 ---
    op.execute("""
        INSERT INTO residual_interactions (drug1_id, drug2_id, interaction_type, mechanism)
        SELECT p.d1, p.d2, 'duplicate_effect_group', '효능군 중복: ' || p.effect_name
        FROM (
            SELECT DISTINCT
                least(a.drug_id, b.drug_id) AS d1,
                greatest(a.drug_id, b.drug_id) AS d2,
                a.effect_name
            FROM drug_effect_groups a
            JOIN drug_effect_groups b ON a.dur_seq = b.dur_seq AND a.drug_id < b.drug_id
        ) p
        WHERE NOT EXISTS (
            SELECT 1
            FROM drug_ingredients a
            JOIN dur_ingredient_effect_groups ea ON ea.ingr_code = a.ingr_code
            JOIN dur_ingredient_effect_groups eb ON eb.dur_seq = ea.dur_seq
            JOIN drug_ingredients b ON b.drug_id = p.d2 AND b.ingr_code = eb.ingr_code
            WHERE a.drug_id = p.d1
        )
    """)

    op.drop_table("drug_interactions")
    op.drop_table("drug_effect_groups")


def downgrade() -> None:
    # 데이터는 복구하지 않는다(재sync 필요) — 스키마만 되돌린다.
    op.create_table(
        "drug_effect_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("drug_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dur_seq", sa.String(20), nullable=False),
        sa.Column("effect_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("drug_id", "dur_seq", name="uq_drug_effect_groups_drug_dur_seq"),
    )
    op.create_index("idx_drug_effect_groups_dur_seq", "drug_effect_groups", ["dur_seq"])
    op.create_index("ix_drug_effect_groups_drug_id", "drug_effect_groups", ["drug_id"])

    op.create_table(
        "drug_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("drug1_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drug2_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interaction_type", sa.String(20), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_drug_interactions_pair", "drug_interactions", ["drug1_id", "drug2_id"])
    op.create_index("ix_drug_interactions_drug1_id", "drug_interactions", ["drug1_id"])
    op.create_index("ix_drug_interactions_drug2_id", "drug_interactions", ["drug2_id"])

    op.drop_table("residual_interactions")
