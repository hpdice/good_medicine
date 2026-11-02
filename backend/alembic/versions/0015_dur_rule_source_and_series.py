"""DUR 판정 규칙에 출처(source) + 효능군 계열(sers_name)

규칙을 DUR 성분정보(`DURIrdntInfoService03`)로 보강하면서, 기존 품목정보 유래 행('product')과
새 행('ingredient')을 구분해 되돌릴 수 있게 한다. 효능군중복은 '효능군 + 계열' 단위로 판정하므로
계열명(SERS_NAME)을 담는다.

Revision ID: 0015_dur_rule_source_series
Revises: 0014_dur_ingredient_master
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_dur_rule_source_series"
down_revision: Union[str, None] = "0014_dur_ingredient_master"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("dur_ingredient_contraindications", "dur_ingredient_effect_groups", "dur_ingredient_age_caution")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("source", sa.String(length=20), server_default="product", nullable=False))
    op.add_column("dur_ingredient_effect_groups", sa.Column("sers_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("dur_ingredient_effect_groups", "sers_name")
    for table in _TABLES:
        op.drop_column(table, "source")
