"""analysis_results 테이블 추가 — 로컬 LLM 기반 AI 대응 가이드(첨언) 이력

Revision ID: 0004_analysis_results
Revises: 0003_effect_groups
Create Date: 2026-08-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_analysis_results"
down_revision: Union[str, None] = "0003_effect_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("drug_ids", postgresql.JSONB, nullable=False),
        sa.Column("findings_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("action_guide_encrypted", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_analysis_results_user_id", "analysis_results", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_results_user_id", table_name="analysis_results")
    op.drop_table("analysis_results")
