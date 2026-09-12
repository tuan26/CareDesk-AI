"""contact opt-out: a patient who says stop is not contacted again

Marketing only. An appointment reminder for a visit the patient booked
themselves is not marketing, and withholding it would be the opposite of
respecting what they asked for.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("patient_leads")}

    if "contact_opt_out" not in existing:
        # server_default is required, not cosmetic: without it this is
        # "ADD COLUMN ... NOT NULL" with no default, which SQLite accepts on an
        # empty table and refuses on one with rows.
        op.add_column("patient_leads", sa.Column(
            "contact_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.create_index("ix_patient_leads_opt_out", "patient_leads", ["contact_opt_out"])
    if "opt_out_at" not in existing:
        op.add_column("patient_leads",
                      sa.Column("opt_out_at", sa.DateTime(timezone=True), nullable=True))
    if "opt_out_reason" not in existing:
        op.add_column("patient_leads", sa.Column("opt_out_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("patient_leads", "opt_out_reason")
    op.drop_column("patient_leads", "opt_out_at")
    op.drop_index("ix_patient_leads_opt_out", table_name="patient_leads")
    op.drop_column("patient_leads", "contact_opt_out")
