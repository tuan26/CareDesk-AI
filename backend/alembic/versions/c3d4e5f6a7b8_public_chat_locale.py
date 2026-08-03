"""public chat session and locale fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("clinics") as batch_op:
        batch_op.add_column(sa.Column("default_locale", sa.String(), nullable=False, server_default="vi"))
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(sa.Column("locale", sa.String(), nullable=True))
    with op.batch_alter_table("services") as batch_op:
        batch_op.add_column(sa.Column("localized_content", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("services") as batch_op:
        batch_op.drop_column("localized_content")
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("locale")
    with op.batch_alter_table("clinics") as batch_op:
        batch_op.drop_column("default_locale")
