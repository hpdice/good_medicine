"""쓰지 않는 테이블·열 삭제

- dur_ingredient_ori: DUR 원 성분 코드([M…]·[I…]). 허가정보 M코드와 같은 체계임은 확인했지만, 성분코드가 없는 약에는
  M코드 자체가 없어 해소에 쓸 곳이 없다(실측 기여 0).
- dur_ingredient_master.ingr_kor_norm·source_endpoints: 한글명 매칭 경로(기여 0)와 기록용 출처 라벨 — 읽는 곳 없음.
- users.phone_number: 수집하는 화면이 없고 값도 없다. 쓰지 않는 개인정보 칸.
- drugs.item_permit_date: 동기화가 채우기만 하고 앱·판정 어디서도 읽지 않는다.

Revision ID: 0017_drop_unused
Revises: 0016_hira_master
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0017_drop_unused"
down_revision: Union[str, None] = "0016_hira_master"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_dur_ingr_ori_ori_code", table_name="dur_ingredient_ori")
    op.drop_table("dur_ingredient_ori")
    op.drop_index("idx_dur_ingr_master_kor_norm", table_name="dur_ingredient_master")
    op.drop_column("dur_ingredient_master", "ingr_kor_norm")
    op.drop_column("dur_ingredient_master", "source_endpoints")
    op.drop_column("users", "phone_number")
    op.drop_column("drugs", "item_permit_date")


def downgrade() -> None:
    op.add_column("drugs", sa.Column("item_permit_date", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("phone_number", sa.String(length=20), nullable=True))
    op.add_column("dur_ingredient_master", sa.Column(
        "source_endpoints", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("dur_ingredient_master", sa.Column("ingr_kor_norm", sa.String(length=300), nullable=True))
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
