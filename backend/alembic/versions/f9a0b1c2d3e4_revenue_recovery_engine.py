"""revenue recovery engine: opportunities + per-service revisit interval

Adds the one table the recovery loop hangs off, plus the single field that makes
"overdue revisit" possible at all. Nothing infers a revisit interval — services
start NULL, meaning "one-off, never chase", which is the only safe default: a
guessed number turns straight into the clinic messaging people who were never
due back.

Revision ID: f9a0b1c2d3e4
Revises: d2e3f4a5b6c7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f9a0b1c2d3e4'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if not _has_column("services", "revisit_interval_days"):
        op.add_column("services", sa.Column("revisit_interval_days", sa.Integer(), nullable=True))

    if "revenue_opportunities" in tables:
        return

    op.create_table(
        "revenue_opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clinic_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("opportunity_type", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False, server_default=""),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("patient_package_id", sa.Integer(), nullable=True),
        sa.Column("appointment_id", sa.Integer(), nullable=True),
        sa.Column("booking_request_id", sa.Integer(), nullable=True),
        sa.Column("estimated_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("probability", sa.Float(), nullable=False, server_default="0"),
        sa.Column("urgency_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("recommended_channel", sa.String(), nullable=True),
        sa.Column("recommended_message", sa.Text(), nullable=True),
        sa.Column("recommended_offer", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("is_holdout", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_appointment_id", sa.Integer(), nullable=True),
        sa.Column("recovered_amount", sa.Float(), nullable=True),
        sa.Column("loss_reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patient_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["patient_package_id"], ["patient_packages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["booking_request_id"], ["booking_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_appointment_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "opportunity_type", "patient_id", "dedupe_key",
                            name="uq_revenue_opportunity_subject"),
    )
    op.create_index("ix_revenue_opportunities_clinic_id", "revenue_opportunities", ["clinic_id"])
    op.create_index("ix_revenue_opportunities_patient_id", "revenue_opportunities", ["patient_id"])
    op.create_index("ix_revenue_opportunities_type", "revenue_opportunities", ["opportunity_type"])
    op.create_index("ix_revenue_opportunities_status", "revenue_opportunities", ["status"])
    op.create_index("ix_revenue_opportunities_holdout", "revenue_opportunities", ["is_holdout"])


def downgrade() -> None:
    op.drop_table("revenue_opportunities")
    if _has_column("services", "revisit_interval_days"):
        op.drop_column("services", "revisit_interval_days")
