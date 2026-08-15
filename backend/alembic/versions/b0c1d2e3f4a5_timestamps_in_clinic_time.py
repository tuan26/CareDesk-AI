"""Move stored timestamps from UTC to clinic time.

Two clocks were writing to the same columns. `server_default=func.now()` is
CURRENT_TIMESTAMP, which SQLite and Postgres both give in UTC; everything the
application wrote used the machine clock. On a Vietnamese laptop that is a
seven-hour gap inside one table — the inbox showed messages seven hours old the
moment they arrived, and every "hôm nay" report compared a UTC column against a
local range and counted the wrong day at both ends.

The application now writes every timestamp through backend.app.core.clock, so
new rows are consistent. This shifts the rows already there.

Safe to do wholesale: no code path ever passed created_at explicitly, so every
existing value came from CURRENT_TIMESTAMP and every one of them is UTC. The
columns that Python *did* write (first_seen_at, consent_timestamp, sent_at, the
booking lifecycle stamps) are deliberately left alone — they were already in
machine-local time, which on this deployment is clinic time.

Reversible, and idempotent in the sense that matters: down() shifts back.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b0c1d2e3f4a5'
down_revision: Union[str, None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Vietnam has held a single offset with no daylight saving since 1975, so a
#: fixed shift is exact for every row rather than an approximation.
_OFFSET_HOURS = 7

#: (table, column) pairs whose values were only ever written by the database
#: default. Anything Python assigned is excluded — shifting those would move
#: correct data seven hours into the future.
_COLUMNS = [
    ("conversations", "created_at"),
    ("messages", "created_at"),
    ("patient_leads", "created_at"),
    ("appointments", "created_at"),
    ("booking_requests", "created_at"),
    ("revenue_records", "created_at"),
    ("clinics", "created_at"),
    ("branches", "created_at"),
    ("users", "created_at"),
    ("services", "created_at"),
    ("doctors", "created_at"),
]


def _shift(hours: int) -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    inspector = sa.inspect(conn)
    present = set(inspector.get_table_names())

    for table, column in _COLUMNS:
        if table not in present:
            continue
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            continue
        if dialect == "sqlite":
            expr = f"datetime({column}, '{hours:+d} hours')"
        else:
            expr = f"{column} + INTERVAL '{hours} hours'"
        conn.execute(sa.text(
            f"UPDATE {table} SET {column} = {expr} WHERE {column} IS NOT NULL"))


def upgrade() -> None:
    _shift(_OFFSET_HOURS)


def downgrade() -> None:
    _shift(-_OFFSET_HOURS)
