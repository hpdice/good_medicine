"""심평원 약가마스터: 품목 ↔ 일반명코드(hira_item_gen_codes), 일반명코드 성분 구성(hira_gen_ingredients)

Revision ID: 0016_hira_master
Revises: 0015_dur_rule_source_series
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_hira_master"
down_revision: Union[str, None] = "0015_dur_rule_source_series"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hira_item_gen_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_seq", sa.String(length=20), nullable=False),
        sa.Column("gen_code", sa.String(length=9), nullable=False),
        sa.Column("etc_otc", sa.String(length=10), nullable=True),
        sa.Column("atc_code", sa.String(length=10), nullable=True),
        sa.Column("cancelled_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_seq", "gen_code", name="uq_hira_item_gen_code"),
    )
    op.create_index("idx_hira_item_gen_code_gen", "hira_item_gen_codes", ["gen_code"], unique=False)

    op.create_table(
        "hira_gen_ingredients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("gen_code", sa.String(length=9), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ingr_name", sa.String(length=300), nullable=False),
        sa.Column("form_code", sa.String(length=4), nullable=True),
        sa.Column("form_name", sa.String(length=50), nullable=True),
        sa.Column("route", sa.String(length=10), nullable=True),
        sa.Column("strength", sa.String(length=20), nullable=True),
        sa.Column("unit", sa.String(length=60), nullable=True),
        sa.Column("class_no", sa.String(length=5), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gen_code", "seq", name="uq_hira_gen_ingredient_seq"),
    )


def downgrade() -> None:
    op.drop_table("hira_gen_ingredients")
    op.drop_index("idx_hira_item_gen_code_gen", table_name="hira_item_gen_codes")
    op.drop_table("hira_item_gen_codes")
