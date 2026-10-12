"""DUR 임부금기(품목 단위) 테이블 + users.pregnancy_encrypted

Revision ID: 0011_pregnancy_taboo
Revises: 0010_drop_identification
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_pregnancy_taboo"
down_revision: Union[str, None] = "0010_drop_identification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dur_item_pregnancy_taboo",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_seq", sa.String(length=50), nullable=False),
        sa.Column("ingr_code", sa.String(length=20), nullable=False),
        sa.Column("ingr_kor", sa.String(length=200), nullable=True),
        sa.Column("prohibit_content", sa.Text(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_seq", "ingr_code", name="uq_dur_item_pregnancy_item_ingr"),
    )
    op.create_index("idx_dur_item_pregnancy_item_seq", "dur_item_pregnancy_taboo", ["item_seq"], unique=False)
    op.add_column("users", sa.Column("pregnancy_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "pregnancy_encrypted")
    op.drop_index("idx_dur_item_pregnancy_item_seq", table_name="dur_item_pregnancy_taboo")
    op.drop_table("dur_item_pregnancy_taboo")
