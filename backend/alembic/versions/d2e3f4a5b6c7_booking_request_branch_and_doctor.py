"""Record which location and which doctor a request is for.

Both are known when the request is made — the chat pins a branch when the
patient arrives and names a doctor before it quotes times — and both were
dropped. Reception saw a request with no clinic and no doctor and had to reopen
the conversation to find out, which is the manual step the queue exists to
remove.

The web form did keep the branch, by appending its name to the preferred time:
"10:30 16/08/2026 — Chi nhánh Quận 10". Free text in a column nobody can filter
or assign by, and the chat wrote "2026-08-16 18:00" into the same column, so the
one list showed two formats. preferred_at makes the time a timestamp;
preferred_time keeps whatever the patient actually said, because "chiều thứ 5
nào cũng được" is a legitimate answer no column can hold.

Existing rows keep their strings. Parsing a branch name back out of free text
would be guesswork, and a wrong branch is worse than a blank one.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('booking_requests', sa.Column('branch_id', sa.Integer(), nullable=True))
    op.add_column('booking_requests', sa.Column('doctor_id', sa.Integer(), nullable=True))
    op.add_column('booking_requests',
                  sa.Column('preferred_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_booking_requests_branch_id', 'booking_requests', ['branch_id'])
    op.create_index('ix_booking_requests_doctor_id', 'booking_requests', ['doctor_id'])
    op.create_index('ix_booking_requests_preferred_at', 'booking_requests', ['preferred_at'])


def downgrade() -> None:
    op.drop_index('ix_booking_requests_preferred_at', table_name='booking_requests')
    op.drop_index('ix_booking_requests_doctor_id', table_name='booking_requests')
    op.drop_index('ix_booking_requests_branch_id', table_name='booking_requests')
    op.drop_column('booking_requests', 'preferred_at')
    op.drop_column('booking_requests', 'doctor_id')
    op.drop_column('booking_requests', 'branch_id')
