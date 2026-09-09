"""성분 테이블에서 write-only(코드에서 안 읽는) 컬럼 제거

Revision ID: 0007_drop_unused_ingr_cols
Revises: 0006_residual_interactions
Create Date: 2026-09-01

sweep이 채우기만 하고 판정/조회 로직이 전혀 읽지 않던 컬럼들을 뺀다.
필요해지면 1줄 마이그레이션 + sweep 재실행으로 되살릴 수 있다.
  drug_ingredients               : ingr_eng, amount(애초에 안 채워짐)
  dur_ingredient_contraindications: class_a, class_b, dur_seq
  dur_ingredient_effect_groups   : ingr_kor, sers_name
(ingr_kor_a/b, prohibit_content, remark, 효능군 dur_seq/effect_name 은 읽히므로 유지)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_drop_unused_ingr_cols"
down_revision: Union[str, None] = "0006_residual_interactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("drug_ingredients", "ingr_eng")
    op.drop_column("drug_ingredients", "amount")
    op.drop_column("dur_ingredient_contraindications", "class_a")
    op.drop_column("dur_ingredient_contraindications", "class_b")
    op.drop_column("dur_ingredient_contraindications", "dur_seq")
    op.drop_column("dur_ingredient_effect_groups", "ingr_kor")
    op.drop_column("dur_ingredient_effect_groups", "sers_name")


def downgrade() -> None:
    op.add_column("dur_ingredient_effect_groups", sa.Column("sers_name", sa.String(200), nullable=True))
    op.add_column("dur_ingredient_effect_groups", sa.Column("ingr_kor", sa.String(200), nullable=True))
    op.add_column("dur_ingredient_contraindications", sa.Column("dur_seq", sa.String(20), nullable=True))
    op.add_column("dur_ingredient_contraindications", sa.Column("class_b", sa.String(200), nullable=True))
    op.add_column("dur_ingredient_contraindications", sa.Column("class_a", sa.String(200), nullable=True))
    op.add_column("drug_ingredients", sa.Column("amount", sa.String(100), nullable=True))
    op.add_column("drug_ingredients", sa.Column("ingr_eng", sa.String(300), nullable=True))
