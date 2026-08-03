"""stateful public sessions and administrative booking requests

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "public_chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("previous_token_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_public_chat_sessions_conversation_id", "public_chat_sessions", ["conversation_id"])
    op.create_index("ix_public_chat_sessions_expires_at", "public_chat_sessions", ["expires_at"])
    op.create_index("ix_public_chat_sessions_revoked_at", "public_chat_sessions", ["revoked_at"])
    op.create_index("ix_public_chat_sessions_previous_token_hash", "public_chat_sessions", ["previous_token_hash"])
    op.create_table(
        "booking_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clinic_id", sa.Integer(), sa.ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patient_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True),
        sa.Column("locale", sa.String(), nullable=False, server_default="vi"),
        sa.Column("service_or_need", sa.Text(), nullable=False),
        sa.Column("preferred_time", sa.String(), nullable=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("contact_method", sa.String(), nullable=False, server_default="phone"),
        sa.Column("contact_value", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="requested"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_booking_requests_clinic_id", "booking_requests", ["clinic_id"])
    op.create_index("ix_booking_requests_conversation_id", "booking_requests", ["conversation_id"])
    op.create_index("ix_booking_requests_patient_id", "booking_requests", ["patient_id"])
    op.create_index("ix_booking_requests_status", "booking_requests", ["status"])


def downgrade() -> None:
    op.drop_table("booking_requests")
    op.drop_table("public_chat_sessions")
