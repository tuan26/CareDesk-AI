"""Deposit holds get a deadline, and the database refuses double-booked slots.

Two halves of the same bug. `awaiting_deposit` was not counted as occupying the
slot, so a patient away paying their deposit had that time offered to the next
person who asked. Counting it fixes the common case — but the check happens in
Python, read-then-write with no lock, so two people confirming at the same
instant could still both land on the same slot. A partial unique index makes the
database the final arbiter.

The hold deadline exists because holding a slot with no expiry is its own
outage: one abandoned payment page locks a prime evening slot until a human
notices.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LIVE = "status IN ('pending', 'awaiting_deposit', 'confirmed')"


def upgrade() -> None:
    op.add_column('appointments',
                  sa.Column('hold_expires_at', sa.DateTime(timezone=True), nullable=True))

    # Refuse to build the index over data that already violates it: a partial
    # unique index on duplicates fails with an opaque error mid-deploy. Name the
    # offending rows instead so they can be fixed in a couple of minutes.
    conn = op.get_bind()
    dupes = conn.execute(sa.text(
        f"SELECT doctor_id, start_time, COUNT(*) c FROM appointments WHERE {LIVE} "
        "GROUP BY doctor_id, start_time HAVING COUNT(*) > 1"
    )).fetchall()
    if dupes:
        listing = "; ".join(f"bác sĩ #{d[0]} lúc {d[1]} ({d[2]} lịch)" for d in dupes[:10])
        raise RuntimeError(
            f"Có {len(dupes)} khung giờ đang bị đặt trùng, phải xử lý trước khi thêm "
            f"ràng buộc chống trùng: {listing}. "
            "Hãy huỷ hoặc dời các lịch thừa rồi chạy lại migration."
        )

    # Partial index: only live appointments compete for a slot. Cancelled and
    # completed rows must be free to pile up on the same time — otherwise a slot
    # could never be rebooked after a cancellation.
    op.create_index(
        'uq_appointment_live_slot', 'appointments', ['doctor_id', 'start_time'],
        unique=True,
        sqlite_where=sa.text(LIVE),
        postgresql_where=sa.text(LIVE),
    )


def downgrade() -> None:
    op.drop_index('uq_appointment_live_slot', table_name='appointments')
    op.drop_column('appointments', 'hold_expires_at')
