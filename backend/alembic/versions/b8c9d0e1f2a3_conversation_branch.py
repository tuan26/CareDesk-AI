"""remember which branch a public conversation started from

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-03 15:30:00.000000

/chat/<brand>/<branch> resolved only as far as the clinic, so the branch the
patient picked was dropped on the floor. The booking flow then took the first
doctor with a free slot, which meant every conversation booked whichever branch
that doctor worked at — clicking "đặt lịch" on any location always produced the
first one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('branch_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_conversations_branch_id'), ['branch_id'])
        batch_op.create_foreign_key(
            'fk_conversations_branch_id', 'branches', ['branch_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_conversations_branch_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_conversations_branch_id'))
        batch_op.drop_column('branch_id')
