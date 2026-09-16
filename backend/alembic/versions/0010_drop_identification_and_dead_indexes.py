"""낱알식별 컬럼·안 쓰는 인덱스 제거

Revision ID: 0010_drop_identification
Revises: ce94face11b4
Create Date: 2026-09-17

사진 기반 알약 인식 기능은 2026-09-12에 이미 폐기 확정됐는데(CLAUDE.md 참고),
그걸 채우던 drug_shape/color_class1/print_front/print_back과 item_image(다른
소스 3곳에서도 채웠지만 프론트가 전혀 안 읽음)가 DB엔 남아있었다. 전수 grep으로
front_app 어디서도 안 쓰는 것 확인 후 제거.

인덱스 3개도 함께 뺀다 — pg_stat_user_indexes.idx_scan 실측 확인:
  idx_drugs_ingr_name_gin : 0회. ingr_name 조회는 jsonb_array_elements()+ILIKE라
                             GIN이 애초에 가속 못 하는 패턴(구조적으로 죽은 인덱스).
  ix_drugs_item_name      : item_name은 코드 전체에서 .ilike()로만 조회 —
  ix_drugs_simple_name      일반 B-tree로는 못 도와주고 트라이그램 GIN과 중복.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_drop_identification"
down_revision: Union[str, None] = "ce94face11b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_drugs_ingr_name_gin", table_name="drugs")
    op.drop_index("ix_drugs_item_name", table_name="drugs")
    op.drop_index("ix_drugs_simple_name", table_name="drugs")
    op.drop_column("drugs", "drug_shape")
    op.drop_column("drugs", "color_class1")
    op.drop_column("drugs", "print_front")
    op.drop_column("drugs", "print_back")
    op.drop_column("drugs", "item_image")


def downgrade() -> None:
    op.add_column("drugs", sa.Column("drug_shape", sa.String(50), nullable=True))
    op.add_column("drugs", sa.Column("color_class1", sa.String(50), nullable=True))
    op.add_column("drugs", sa.Column("print_front", sa.String(100), nullable=True))
    op.add_column("drugs", sa.Column("print_back", sa.String(100), nullable=True))
    op.add_column("drugs", sa.Column("item_image", sa.String(500), nullable=True))
    op.create_index("ix_drugs_simple_name", "drugs", ["simple_name"])
    op.create_index("ix_drugs_item_name", "drugs", ["item_name"])
    op.create_index("idx_drugs_ingr_name_gin", "drugs", ["ingr_name"], postgresql_using="gin")
