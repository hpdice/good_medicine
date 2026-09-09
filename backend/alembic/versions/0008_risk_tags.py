"""dur_ingredient_contraindications.risk_tags 추가 — prohibit_content에서 LLM이 추출한 위험/증상 태그

Revision ID: 0008_risk_tags
Revises: 0007_drop_unused_ingr_cols
Create Date: 2026-09-01

값은 `sync.py extract_risk_tags`가 로컬 LLM으로 1회 채운다(distinct prohibit_content ~127개).
NULL이면 quick_check finding의 risk_tags가 빈 배열 — 판정엔 영향 없음.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_risk_tags"
down_revision: Union[str, None] = "0007_drop_unused_ingr_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dur_ingredient_contraindications",
        sa.Column("risk_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dur_ingredient_contraindications", "risk_tags")
