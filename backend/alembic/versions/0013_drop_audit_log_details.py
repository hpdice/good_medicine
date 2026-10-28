"""audit_logs.details 삭제 — 코드가 읽거나 쓴 적이 없고 값도 전부 NULL인 컬럼

Revision ID: 0013_drop_audit_log_details
Revises: 0012_drug_detail_fetched_at
Create Date: 2026-10-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013_drop_audit_log_details"
down_revision: Union[str, None] = "0012_drug_detail_fetched_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("audit_logs", "details")


def downgrade() -> None:
    op.add_column("audit_logs", sa.Column("details", postgresql.JSONB(), nullable=True))
