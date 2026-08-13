"""Record which advert paid for each patient.

Until now "source" answered two different questions with one field, and
therefore answered neither. Appointment.booking_source says who typed the
booking in — the AI or a receptionist. PatientLead.source said "web", which is
where they were standing, not where they came from. A clinic asking whether
Facebook is worth the money could not be answered at all: no campaign, no UTM,
no referrer, nothing linking an advert to the revenue it eventually produced.

These columns hold **first touch** specifically. Last touch is easier to capture
and is the wrong thing to report — the retargeting ad that catches someone on
their way back takes credit for a patient the original campaign found, so the
channel that actually works looks worse than the one that finished the job. The
first visit wins and is never overwritten, including for returning patients:
the campaign that earned the relationship keeps it.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f8a9b0c1d2e3'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ("utm_source", sa.String()),      # facebook | google | tiktok | zalo
    ("utm_medium", sa.String()),      # cpc | organic | qr | referral
    ("utm_campaign", sa.String()),    # "pico-thang-8"
    ("utm_content", sa.String()),     # which creative
    ("referrer", sa.String()),        # full referring URL
    ("landing_path", sa.String()),    # which page caught them
    ("first_seen_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column('patient_leads', sa.Column(name, type_, nullable=True))

    # The two the channel report groups by, on every read.
    op.create_index('ix_patient_leads_utm_source', 'patient_leads', ['utm_source'])
    op.create_index('ix_patient_leads_utm_campaign', 'patient_leads', ['utm_campaign'])

    # Existing patients pre-date attribution. Deliberately left NULL rather than
    # guessed: services/attribution.channel_of falls back down a ladder ending at
    # "direct", and inventing a channel for them would put fictional revenue
    # against a real campaign the first time someone reads the report.


def downgrade() -> None:
    op.drop_index('ix_patient_leads_utm_campaign', table_name='patient_leads')
    op.drop_index('ix_patient_leads_utm_source', table_name='patient_leads')
    for name, _ in reversed(_COLUMNS):
        op.drop_column('patient_leads', name)
