"""baseline schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("health_conditions_encrypted", sa.Text(), nullable=True),
        sa.Column("allergy_info_encrypted", sa.Text(), nullable=True),
        sa.Column("privacy_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_data_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fcm_token", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "drugs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_seq", sa.String(20), unique=True, nullable=False),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("drug_key", sa.String(255), nullable=True),
        sa.Column("simple_name", sa.String(255), nullable=True),
        sa.Column("entp_name", sa.String(255), nullable=True),
        sa.Column("item_permit_date", sa.Date(), nullable=True),
        sa.Column("main_item_ingr", sa.Text(), nullable=True),
        sa.Column("ingr_name", postgresql.JSONB(), nullable=True),
        sa.Column("efcy_qesitm", sa.Text(), nullable=True),
        sa.Column("use_method_qesitm", sa.Text(), nullable=True),
        sa.Column("atpn_warn_qesitm", sa.Text(), nullable=True),
        sa.Column("atpn_qesitm", sa.Text(), nullable=True),
        sa.Column("intrc_qesitm", sa.Text(), nullable=True),
        sa.Column("se_qesitm", sa.Text(), nullable=True),
        sa.Column("deposit_method_qesitm", sa.Text(), nullable=True),
        sa.Column("drug_shape", sa.String(50), nullable=True),
        sa.Column("color_class1", sa.String(50), nullable=True),
        sa.Column("print_front", sa.String(100), nullable=True),
        sa.Column("print_back", sa.String(100), nullable=True),
        sa.Column("item_image", sa.String(500), nullable=True),
        sa.Column("class_name", sa.String(100), nullable=True),
        sa.Column("etc_otc_name", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_drugs_item_seq", "drugs", ["item_seq"])
    op.create_index("ix_drugs_item_name", "drugs", ["item_name"])
    op.create_index("ix_drugs_drug_key", "drugs", ["drug_key"])
    op.create_index("ix_drugs_simple_name", "drugs", ["simple_name"])
    op.create_index("idx_drugs_item_name_trgm", "drugs", ["item_name"],
                    postgresql_using="gin", postgresql_ops={"item_name": "gin_trgm_ops"})
    op.create_index("idx_drugs_drug_key_trgm", "drugs", ["drug_key"],
                    postgresql_using="gin", postgresql_ops={"drug_key": "gin_trgm_ops"})
    op.create_index("idx_drugs_simple_name_trgm", "drugs", ["simple_name"],
                    postgresql_using="gin", postgresql_ops={"simple_name": "gin_trgm_ops"})
    op.create_index("idx_drugs_ingr_name_gin", "drugs", ["ingr_name"],
                    postgresql_using="gin")

    op.create_table(
        "drug_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("drug1_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drug2_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interaction_type", sa.String(20), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_drug_interactions_drug1_id", "drug_interactions", ["drug1_id"])
    op.create_index("ix_drug_interactions_drug2_id", "drug_interactions", ["drug2_id"])
    op.create_index("idx_drug_interactions_pair", "drug_interactions", ["drug1_id", "drug2_id"])

    op.create_table(
        "medicine_box_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drug_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prescribed_date", sa.Date(), nullable=True),
        sa.Column("dosage_per_intake", sa.String(50), nullable=True),
        sa.Column("intake_frequency", sa.String(100), nullable=True),
        sa.Column("intake_duration_days", sa.Integer(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("added_method", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_medicine_box_entries_user_id", "medicine_box_entries", ["user_id"])
    op.create_index("ix_medicine_box_entries_drug_id", "medicine_box_entries", ["drug_id"])
    op.create_index("idx_medicine_box_user_current", "medicine_box_entries", ["user_id", "is_current"])


def downgrade() -> None:
    op.drop_table("medicine_box_entries")
    op.drop_table("drug_interactions")
    op.drop_table("drugs")
    op.drop_table("audit_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
