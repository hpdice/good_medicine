"""복약함·분석이력의 개인 복약정보 필드 암호화

Revision ID: 0009_encrypt_medication_data
Revises: 0008_risk_tags
Create Date: 2026-09-09

"누가 무슨 약을 먹는지"는 PIPA상 민감정보(건강정보)다. 기존엔 건강상태/알레르기만
암호화하고 복약함(medicine_box_entries)과 분석이력(analysis_results)의 약품 정보는
평문이었다 — DB/디스크 유출 시 그대로 노출. 이걸 다른 민감필드와 동일하게
AES-256-GCM 필드 암호화로 맞춘다.

- medicine_box_entries: drug_id + 처방 상세(용량/주기/기간/메모/처방일)를
  단일 `payload_encrypted` 블롭으로. drugs FK/CASCADE는 사라진다(공공데이터라
  사실상 append-only, 서비스가 미존재 약품 항목은 조회 시 건너뜀).
  남는 평문 컬럼: user_id, is_current, added_method, created_at, updated_at.
- analysis_results: drug_ids/findings_snapshot(JSONB 평문) → *_encrypted(Text).

기존 평문 행은 마이그레이션에서 옮기지 않는다(암호화는 SQL로 못 함). 배포 전
개발 리셋 상태를 전제로 하며, 운영 데이터가 있다면 별도 백필 스크립트가 필요하다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_encrypt_medication_data"
down_revision: Union[str, None] = "0008_risk_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- medicine_box_entries ---
    op.add_column(
        "medicine_box_entries",
        sa.Column("payload_encrypted", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("medicine_box_entries", "payload_encrypted", server_default=None)

    op.drop_constraint(
        "medicine_box_entries_drug_id_fkey", "medicine_box_entries", type_="foreignkey"
    )
    op.drop_index("ix_medicine_box_entries_drug_id", table_name="medicine_box_entries")
    op.drop_column("medicine_box_entries", "drug_id")
    op.drop_column("medicine_box_entries", "prescribed_date")
    op.drop_column("medicine_box_entries", "dosage_per_intake")
    op.drop_column("medicine_box_entries", "intake_frequency")
    op.drop_column("medicine_box_entries", "intake_duration_days")
    op.drop_column("medicine_box_entries", "notes")

    # --- analysis_results ---
    op.add_column(
        "analysis_results",
        sa.Column("drug_ids_encrypted", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "analysis_results",
        sa.Column("findings_snapshot_encrypted", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("analysis_results", "drug_ids_encrypted", server_default=None)
    op.alter_column("analysis_results", "findings_snapshot_encrypted", server_default=None)
    op.drop_column("analysis_results", "drug_ids")
    op.drop_column("analysis_results", "findings_snapshot")


def downgrade() -> None:
    # --- analysis_results ---
    op.add_column(
        "analysis_results",
        sa.Column("findings_snapshot", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "analysis_results",
        sa.Column("drug_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.alter_column("analysis_results", "findings_snapshot", server_default=None)
    op.alter_column("analysis_results", "drug_ids", server_default=None)
    op.drop_column("analysis_results", "findings_snapshot_encrypted")
    op.drop_column("analysis_results", "drug_ids_encrypted")

    # --- medicine_box_entries ---
    op.add_column(
        "medicine_box_entries",
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "medicine_box_entries",
        sa.Column("intake_duration_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "medicine_box_entries",
        sa.Column("intake_frequency", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "medicine_box_entries",
        sa.Column("dosage_per_intake", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "medicine_box_entries",
        sa.Column("prescribed_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "medicine_box_entries",
        sa.Column("drug_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "medicine_box_entries_drug_id_fkey",
        "medicine_box_entries", "drugs",
        ["drug_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index(
        "ix_medicine_box_entries_drug_id", "medicine_box_entries", ["drug_id"]
    )
    op.drop_column("medicine_box_entries", "payload_encrypted")
