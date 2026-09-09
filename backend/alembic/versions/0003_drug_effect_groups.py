"""drug_effect_groups 테이블 추가 — DUR 효능군중복주의

Revision ID: 0003_effect_groups
Revises: 0002_unordered_pair_unique
Create Date: 2026-07-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_effect_groups"
down_revision: Union[str, None] = "0002_unordered_pair_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drug_effect_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "drug_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("dur_seq", sa.String(20), nullable=False),
        sa.Column("effect_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("drug_id", "dur_seq", name="uq_drug_effect_groups_drug_dur_seq"),
    )
    op.create_index("idx_drug_effect_groups_dur_seq", "drug_effect_groups", ["dur_seq"])
    op.create_index("ix_drug_effect_groups_drug_id", "drug_effect_groups", ["drug_id"])


def downgrade() -> None:
    op.drop_index("ix_drug_effect_groups_drug_id", table_name="drug_effect_groups")
    op.drop_index("idx_drug_effect_groups_dur_seq", table_name="drug_effect_groups")
    op.drop_table("drug_effect_groups")
