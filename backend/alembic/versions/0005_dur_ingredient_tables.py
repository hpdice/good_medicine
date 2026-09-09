"""성분 단위 DUR 판정 테이블 추가 — drug_ingredients + dur_ingredient_contraindications + dur_ingredient_effect_groups

Revision ID: 0005_dur_ingredient_tables
Revises: 0004_analysis_results
Create Date: 2026-09-01

품목(item) 단위 drug_interactions / drug_effect_groups는 그대로 두고, 성분(ingredient)
단위 판정 경로용 테이블을 추가한다. 데이터는 기존 DUR sweep
(DURPrdlstInfoService03/getUsjntTabooInfoList03, getEfcyDplctInfoList03) 응답의
INGR_CODE에서 채운다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_dur_ingredient_tables"
down_revision: Union[str, None] = "0004_analysis_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drug_ingredients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "drug_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("ingr_code", sa.String(20), nullable=True),
        sa.Column("ingr_kor", sa.String(200), nullable=True),
        sa.Column("ingr_eng", sa.String(300), nullable=True),
        sa.Column("amount", sa.String(100), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="dur"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("drug_id", "ingr_code", name="uq_drug_ingredients_drug_ingr_code"),
    )
    op.create_index("ix_drug_ingredients_drug_id", "drug_ingredients", ["drug_id"])
    op.create_index("idx_drug_ingredients_ingr_code", "drug_ingredients", ["ingr_code"])

    op.create_table(
        "dur_ingredient_contraindications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ingr_code_a", sa.String(20), nullable=False),
        sa.Column("ingr_code_b", sa.String(20), nullable=False),
        sa.Column("ingr_kor_a", sa.String(200), nullable=True),
        sa.Column("ingr_kor_b", sa.String(200), nullable=True),
        sa.Column("prohibit_content", sa.Text(), nullable=True),
        sa.Column("class_a", sa.String(200), nullable=True),
        sa.Column("class_b", sa.String(200), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("dur_seq", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ingr_code_a", "ingr_code_b", name="uq_dur_ingr_contra_pair"),
    )
    op.create_index("idx_dur_ingr_contra_a", "dur_ingredient_contraindications", ["ingr_code_a"])
    op.create_index("idx_dur_ingr_contra_b", "dur_ingredient_contraindications", ["ingr_code_b"])

    op.create_table(
        "dur_ingredient_effect_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ingr_code", sa.String(20), nullable=False),
        sa.Column("ingr_kor", sa.String(200), nullable=True),
        sa.Column("dur_seq", sa.String(20), nullable=False),
        sa.Column("effect_name", sa.String(200), nullable=False),
        sa.Column("sers_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ingr_code", "dur_seq", name="uq_dur_ingr_effect_ingr_dur_seq"),
    )
    op.create_index("idx_dur_ingr_effect_dur_seq", "dur_ingredient_effect_groups", ["dur_seq"])
    op.create_index("idx_dur_ingr_effect_ingr_code", "dur_ingredient_effect_groups", ["ingr_code"])


def downgrade() -> None:
    op.drop_index("idx_dur_ingr_effect_ingr_code", table_name="dur_ingredient_effect_groups")
    op.drop_index("idx_dur_ingr_effect_dur_seq", table_name="dur_ingredient_effect_groups")
    op.drop_table("dur_ingredient_effect_groups")

    op.drop_index("idx_dur_ingr_contra_b", table_name="dur_ingredient_contraindications")
    op.drop_index("idx_dur_ingr_contra_a", table_name="dur_ingredient_contraindications")
    op.drop_table("dur_ingredient_contraindications")

    op.drop_index("idx_drug_ingredients_ingr_code", table_name="drug_ingredients")
    op.drop_index("ix_drug_ingredients_drug_id", table_name="drug_ingredients")
    op.drop_table("drug_ingredients")
