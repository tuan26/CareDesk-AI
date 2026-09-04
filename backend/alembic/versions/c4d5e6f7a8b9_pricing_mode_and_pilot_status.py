"""pricing mode and pilot status: stop inferring commercial terms from a zero

monthly_fee = 0 means three different things — not configured yet, free pilot,
sponsored — and ROI is the one number that must never be computed from a figure
nobody confirmed. The meaning now has its own column.

Backfill is deliberately conservative: a clinic with a fee already set becomes
"paid", and everything else becomes "unconfigured" rather than "pilot_free".
Guessing that a zero meant a free pilot would be exactly the inference this
migration exists to remove.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = (
    ("pricing_mode", sa.String(), "unconfigured"),
    ("pilot_status", sa.String(), "none"),
    ("pilot_started_at", sa.DateTime(timezone=True), None),
    ("pilot_ended_at", sa.DateTime(timezone=True), None),
)


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("clinics")}

    for name, kind, default in _NEW_COLUMNS:
        if name in existing:
            continue
        # A column with no default has to stay nullable. Getting this backwards
        # produced "ADD COLUMN pilot_started_at DATETIME NOT NULL", which SQLite
        # accepts on an empty table and refuses on one with rows — so it passed
        # every check against a fresh database and failed on the first real one.
        op.add_column("clinics", sa.Column(
            name, kind,
            nullable=default is None,
            server_default=default,
        ))

    # Backfill runs independently of whether the column was added just now. A
    # first attempt that failed after ADD COLUMN but before this left every
    # clinic at "unconfigured" including the ones already paying, and tying the
    # two together meant a retry silently skipped the repair.
    #
    # Only touches rows still sitting at the default, so a deliberate choice —
    # a paying clinic marked sponsored, say — is never overwritten by a re-run.
    op.execute("""
        UPDATE clinics
           SET pricing_mode = 'paid'
         WHERE monthly_fee > 0
           AND (pricing_mode IS NULL OR pricing_mode = 'unconfigured')
    """)


def downgrade() -> None:
    for name, _, _ in reversed(_NEW_COLUMNS):
        op.drop_column("clinics", name)
