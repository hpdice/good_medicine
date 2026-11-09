"""hira_gen_codes — 일반명코드에만 종속된 제형·투여경로·분류를 성분 행에서 분리(2NF)

Revision ID: 0020_hira_gen_codes
Revises: 0019_drugs_master
Create Date: 2026-11-09

hira_gen_ingredients의 form_code/form_name/route/class_no는 (일반명코드, 순번) 키 중 일반명코드에만 종속이라
성분 행마다 같은 값이 되풀이됐다(복합제 7,783개 코드에서 값 충돌 0건). 일반명코드당 1행인 hira_gen_codes로 옮기고
성분 행은 외래 키로 잇는다. 한 코드의 성분 행 중 일부만 값이 비어 있으면 비어 있지 않은 값을 쓴다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0020_hira_gen_codes"
down_revision: Union[str, None] = "0019_drugs_master"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hira_gen_codes",
        sa.Column("gen_code", sa.String(length=9), nullable=False),
        sa.Column("form_code", sa.String(length=4), nullable=True),
        sa.Column("form_name", sa.String(length=50), nullable=True),
        sa.Column("route", sa.String(length=10), nullable=True),
        sa.Column("class_no", sa.String(length=5), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("gen_code", name="hira_gen_codes_pkey"),
    )
    op.execute(
        """
        INSERT INTO hira_gen_codes (gen_code, form_code, form_name, route, class_no)
        SELECT gen_code, min(form_code), min(form_name), min(route), min(class_no)
          FROM hira_gen_ingredients GROUP BY gen_code
        """
    )
    op.create_foreign_key(
        "fk_hira_gen_ingredients_gen_code", "hira_gen_ingredients", "hira_gen_codes",
        ["gen_code"], ["gen_code"], ondelete="CASCADE",
    )
    for col in ("form_code", "form_name", "route", "class_no"):
        op.drop_column("hira_gen_ingredients", col)


def downgrade() -> None:
    op.add_column("hira_gen_ingredients", sa.Column("form_code", sa.String(length=4), nullable=True))
    op.add_column("hira_gen_ingredients", sa.Column("form_name", sa.String(length=50), nullable=True))
    op.add_column("hira_gen_ingredients", sa.Column("route", sa.String(length=10), nullable=True))
    op.add_column("hira_gen_ingredients", sa.Column("class_no", sa.String(length=5), nullable=True))
    op.execute(
        """
        UPDATE hira_gen_ingredients i
           SET form_code = c.form_code, form_name = c.form_name, route = c.route, class_no = c.class_no
          FROM hira_gen_codes c WHERE c.gen_code = i.gen_code
        """
    )
    op.drop_constraint("fk_hira_gen_ingredients_gen_code", "hira_gen_ingredients", type_="foreignkey")
    op.drop_table("hira_gen_codes")
