"""add opt-in public chat V1 flag

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Non-null default keeps every existing widget on legacy behaviour until
    # a clinic is deliberately enrolled in the V1 pilot.
    with op.batch_alter_table("clinics") as batch_op:
        batch_op.add_column(
            sa.Column("public_chat_v1_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("clinics") as batch_op:
        batch_op.drop_column("public_chat_v1_enabled")
