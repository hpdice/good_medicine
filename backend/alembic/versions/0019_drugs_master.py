"""drugs_master — 약 1행으로 모은 통합 데이터셋

Revision ID: 0019_drugs_master
Revises: 0018_dose_caution
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0019_drugs_master"
down_revision: Union[str, None] = "0018_dose_caution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.create_index("idx_drugs_master_status", "drugs_master", ["ingredient_status"], unique=False)
    op.create_index(
        "idx_drugs_master_dur_codes", "drugs_master", ["dur_ingr_codes"], unique=False, postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("idx_drugs_master_dur_codes", table_name="drugs_master", postgresql_using="gin")
    op.drop_index("idx_drugs_master_status", table_name="drugs_master")
    op.drop_table("drugs_master")
