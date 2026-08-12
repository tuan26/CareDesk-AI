"""booking_requests.created_at was always NULL, and it 500'd the staff screen.

Migration e5f6a7b8c9d0 declared created_at as a plain nullable DATETIME while the
model declares server_default=func.now(). SQLAlchemy does not send a value for a
server-default column — it expects the database to fill it — so with no DEFAULT
in the DDL every row was written with NULL.

The consequence was not cosmetic. BookingRequestOut types created_at as a
datetime, so listing them raised ResponseValidationError and
GET /api/v1/booking-requests answered 500. Every booking made through the chat
was recorded correctly and was then invisible to the people who had to act on
it: from the clinic's side the AI simply never booked anyone.

public_chat_sessions has the same defect from the same migration and is fixed
alongside it.

SQLite cannot ALTER a column default, so the tables are rebuilt. Both are small
and young, and batch_alter_table handles the copy.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("booking_requests", "public_chat_sessions")


def upgrade() -> None:
    conn = op.get_bind()

    # Existing rows first: they have to satisfy the column before it is rebuilt,
    # and a booking request with no timestamp is still a real request somebody
    # is waiting on. Nothing better than "now" is recoverable.
    for table in _TABLES:
        conn.execute(sa.text(
            f"UPDATE {table} SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        ))

    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "created_at",
                existing_type=sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "created_at",
                existing_type=sa.DateTime(timezone=True),
                server_default=None,
                nullable=True,
            )
