"""Record why a human was called for.

"Handoff" was one flag covering two situations that need opposite behaviour: a
receptionist typing right now, and a receptionist who has been asked for and has
not arrived. The second can last all night, and the assistant was silenced for
the whole of it — patients asked answerable questions into a void and left.

Telling them apart needs the reason. A safety trigger still silences the
assistant completely; "em không có thông tin đó" does not.

Existing rows get no reason, which reads as "not a muting reason" — correct for
almost all of them, and the safe direction: the worst case is that a patient in
an already-abandoned conversation gets an answer instead of silence.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('handoff_reason', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'handoff_reason')
