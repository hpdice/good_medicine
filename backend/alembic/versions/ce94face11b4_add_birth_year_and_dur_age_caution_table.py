"""add birth_year and dur age caution table

Revision ID: ce94face11b4
Revises: 0009_encrypt_medication_data
Create Date: 2026-09-12 06:33:59.435815

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ce94face11b4'
down_revision: Union[str, None] = '0009_encrypt_medication_data'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('dur_ingredient_age_caution',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('ingr_code', sa.String(length=20), nullable=False),
    sa.Column('ingr_kor', sa.String(length=200), nullable=True),
    sa.Column('rule_type', sa.String(length=20), nullable=False),
    sa.Column('prohibit_content', sa.Text(), nullable=True),
    sa.Column('age_threshold', sa.Integer(), nullable=True),
    sa.Column('age_unit', sa.String(length=10), nullable=True),
    sa.Column('age_direction', sa.String(length=10), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ingr_code', 'rule_type', name='uq_dur_ingr_age_caution_code_type')
    )
    op.create_index('idx_dur_ingr_age_caution_code', 'dur_ingredient_age_caution', ['ingr_code'], unique=False)
    op.add_column('users', sa.Column('birth_year_encrypted', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'birth_year_encrypted')
    op.drop_index('idx_dur_ingr_age_caution_code', table_name='dur_ingredient_age_caution')
    op.drop_table('dur_ingredient_age_caution')
