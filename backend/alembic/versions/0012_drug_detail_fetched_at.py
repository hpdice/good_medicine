"""drugs.detail_fetched_at — 허가정보 상세 API 온디맨드 보강 시각

Revision ID: 0012_drug_detail_fetched_at
Revises: 0011_pregnancy_taboo
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_drug_detail_fetched_at"
down_revision: Union[str, None] = "0011_pregnancy_taboo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drugs", sa.Column("detail_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("drugs", "detail_fetched_at")
