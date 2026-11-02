"""DUR 성분정보 조회표(dur_ingredient_master) + 원 성분 코드(dur_ingredient_ori)

Revision ID: 0014_dur_ingredient_master
Revises: 0013_drop_audit_log_details
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014_dur_ingredient_master"
down_revision: Union[str, None] = "0013_drop_audit_log_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dur_ingredient_master",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ingr_code", sa.String(length=20), nullable=False),
        sa.Column("ingr_kor", sa.String(length=300), nullable=True),
        sa.Column("ingr_eng", sa.String(length=300), nullable=True),
        sa.Column("ingr_kor_norm", sa.String(length=300), nullable=True),
        sa.Column("ingr_eng_norm", sa.String(length=300), nullable=True),
        sa.Column("mix_type", sa.String(length=20), nullable=True),
        sa.Column("source_endpoints", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingr_code", "ingr_kor", "ingr_eng",
            name="uq_dur_ingr_master_code_names", postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("idx_dur_ingr_master_code", "dur_ingredient_master", ["ingr_code"], unique=False)
    op.create_index("idx_dur_ingr_master_eng_norm", "dur_ingredient_master", ["ingr_eng_norm"], unique=False)
    op.create_index("idx_dur_ingr_master_kor_norm", "dur_ingredient_master", ["ingr_kor_norm"], unique=False)

    op.create_table(
        "dur_ingredient_ori",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ingr_code", sa.String(length=20), nullable=False),
        sa.Column("ori_code", sa.String(length=20), nullable=False),
        sa.Column("ori_name", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingr_code", "ori_code", name="uq_dur_ingr_ori_code"),
    )
    op.create_index("idx_dur_ingr_ori_ori_code", "dur_ingredient_ori", ["ori_code"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_dur_ingr_ori_ori_code", table_name="dur_ingredient_ori")
    op.drop_table("dur_ingredient_ori")
    op.drop_index("idx_dur_ingr_master_kor_norm", table_name="dur_ingredient_master")
    op.drop_index("idx_dur_ingr_master_eng_norm", table_name="dur_ingredient_master")
    op.drop_index("idx_dur_ingr_master_code", table_name="dur_ingredient_master")
    op.drop_table("dur_ingredient_master")
