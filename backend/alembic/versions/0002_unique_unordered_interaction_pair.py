"""drug_interactions: 방향 무관 (약품쌍, interaction_type) 유일성 보장

Revision ID: 0002_unordered_pair_unique
Revises: 0001_baseline
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_unordered_pair_unique"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (drug1_id, drug2_id)와 (drug2_id, drug1_id)를 같은 쌍으로 취급하여
    # 동일 쌍이 양방향으로 중복 저장되는 것을 DB 레벨에서 차단한다.
    op.execute(
        """
        CREATE UNIQUE INDEX idx_drug_interactions_unordered_pair_unique
        ON drug_interactions (
            LEAST(drug1_id, drug2_id),
            GREATEST(drug1_id, drug2_id),
            interaction_type
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_drug_interactions_unordered_pair_unique")
