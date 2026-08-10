"""Turn reminder_logs into an outbox: attempts, status and the reason it failed.

The previous revision stopped recording undelivered sends, which fixed the lie
but created a new problem: this table is also the scheduler's "already handled?"
check, so a send that keeps failing is retried on every single tick, forever.
Free while nothing is configured; billed per attempt the moment a real SMS
gateway is in place, and a fast route to a rate limit.

A row now exists from the first attempt. `attempts` bounds the retries,
`last_error` says why, and `medium` separates phone from email so a patient
still gets the email while SMS is broken.

Deliberately NOT counted as an attempt: a send that never reached a provider
because nothing was configured. Otherwise every reminder that queued up while
the clinic waited for its Zalo OA would be retired before the OA arrived.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reminder_logs',
                  sa.Column('medium', sa.String(), nullable=False, server_default='phone'))
    op.add_column('reminder_logs',
                  sa.Column('status', sa.String(), nullable=False, server_default='sent'))
    op.add_column('reminder_logs',
                  sa.Column('attempts', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('reminder_logs', sa.Column('last_error', sa.Text(), nullable=True))
    op.add_column('reminder_logs',
                  sa.Column('updated_at', sa.DateTime(timezone=True),
                            server_default=sa.func.now()))
    op.create_index('ix_reminder_logs_medium', 'reminder_logs', ['medium'])

    # Existing rows were only ever written on success, so 'sent' is correct for
    # all of them. Split them by channel: email rows are the email medium,
    # everything else went to a phone.
    op.get_bind().execute(sa.text(
        "UPDATE reminder_logs SET medium = 'email' WHERE channel = 'email'"
    ))


def downgrade() -> None:
    op.drop_index('ix_reminder_logs_medium', table_name='reminder_logs')
    op.drop_column('reminder_logs', 'updated_at')
    op.drop_column('reminder_logs', 'last_error')
    op.drop_column('reminder_logs', 'attempts')
    op.drop_column('reminder_logs', 'status')
    op.drop_column('reminder_logs', 'medium')
