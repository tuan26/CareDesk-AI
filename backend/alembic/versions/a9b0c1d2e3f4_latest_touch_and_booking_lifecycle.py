"""Keep the last touch too, and timestamp the booking lifecycle.

Two additions that settle arguments rather than add features.

**Latest touch.** First touch owns acquisition credit and must never move, but
throwing the later visits away loses a different, answerable question: what
brought this patient back on the day they finally booked. Stored separately so
assisted-conversion analysis is possible later without anything being able to
overwrite the original attribution.

**Booking lifecycle.** Marketing and operations mean different things by "a
booking" and both are right. Analytics counts the moment the patient asked, so a
channel is never blamed for how long the clinic took to ring back. Operations
needs the whole chain — and the gap between requested and confirmed is a metric
in its own right. "Facebook is underperforming" and "we take four hours to
confirm" look identical in a conversion rate and have completely different
fixes.

Backfilled from what is already known: an appointment that exists was asked for
at least when it was created, and a completed or cancelled one reached that
state no later than its last update.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'f8a9b0c1d2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEAD_COLUMNS = [
    ("utm_term", sa.String()),               # search keyword
    ("click_id", sa.String()),               # fbclid / gclid / ttclid
    ("latest_utm_source", sa.String()),
    ("latest_utm_medium", sa.String()),
    ("latest_utm_campaign", sa.String()),
    ("latest_landing_path", sa.String()),
    ("latest_touch_at", sa.DateTime(timezone=True)),
]

_APPT_COLUMNS = [
    ("booking_requested_at", sa.DateTime(timezone=True)),
    ("booking_confirmed_at", sa.DateTime(timezone=True)),
    ("cancelled_at", sa.DateTime(timezone=True)),
    ("completed_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    for name, type_ in _LEAD_COLUMNS:
        op.add_column('patient_leads', sa.Column(name, type_, nullable=True))
    op.add_column('patient_leads',
                  sa.Column('touch_count', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_patient_leads_latest_utm_source', 'patient_leads',
                    ['latest_utm_source'])

    for name, type_ in _APPT_COLUMNS:
        op.add_column('appointments', sa.Column(name, type_, nullable=True))

    conn = op.get_bind()
    # Every existing appointment was asked for at the moment it was created —
    # the only defensible value, and better than leaving the analytics view
    # blind to everything booked before today.
    conn.execute(sa.text(
        "UPDATE appointments SET booking_requested_at = created_at "
        "WHERE booking_requested_at IS NULL"
    ))
    # Terminal states get their timestamp from created_at as well rather than
    # from now(): stamping them with the migration's clock would make every
    # historical booking look like it was confirmed the day we deployed.
    for status, column in (("confirmed", "booking_confirmed_at"),
                           ("cancelled", "cancelled_at"),
                           ("completed", "completed_at")):
        conn.execute(sa.text(
            f"UPDATE appointments SET {column} = created_at "
            f"WHERE status = '{status}' AND {column} IS NULL"
        ))


def downgrade() -> None:
    for name, _ in reversed(_APPT_COLUMNS):
        op.drop_column('appointments', name)
    op.drop_index('ix_patient_leads_latest_utm_source', table_name='patient_leads')
    op.drop_column('patient_leads', 'touch_count')
    for name, _ in reversed(_LEAD_COLUMNS):
        op.drop_column('patient_leads', name)
