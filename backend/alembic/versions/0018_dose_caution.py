"""DUR 용량주의 규칙(dur_ingredient_dose_caution) + 약 1개당 성분 함량(drug_ingredients.amount_mg)

Revision ID: 0018_dose_caution
Revises: 0017_drop_unused
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0018_dose_caution"
down_revision: Union[str, None] = "0017_drop_unused"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dur_ingredient_dose_caution",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ingr_code", sa.String(length=20), nullable=False),
        sa.Column("ingr_kor", sa.String(length=200), nullable=True),
        sa.Column("mix_codes", sa.String(length=200), server_default="", nullable=False),
        sa.Column("form_name", sa.Text(), server_default="", nullable=False),
        sa.Column("max_qty", sa.String(length=300), nullable=False),
        sa.Column("limits_mg", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prohibit_content", sa.Text(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingr_code", "mix_codes", "form_name", "max_qty", name="uq_dur_ingr_dose_caution_rule"),
    )
    op.create_index("idx_dur_ingr_dose_caution_code", "dur_ingredient_dose_caution", ["ingr_code"], unique=False)
    op.add_column("drug_ingredients", sa.Column("amount_mg", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("drug_ingredients", "amount_mg")
    op.drop_index("idx_dur_ingr_dose_caution_code", table_name="dur_ingredient_dose_caution")
    op.drop_table("dur_ingredient_dose_caution")
