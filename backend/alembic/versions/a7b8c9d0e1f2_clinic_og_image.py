"""clinic social preview image (og:image)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-03 11:00:00.000000

og:image was falling back to `logo_url`, which is the wrong asset for a link
preview: logos are small and square, while Facebook/Zalo want ~1200x630 and drop
anything under 200x200. Clinics need somewhere to put a proper share image.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.add_column(sa.Column('og_image_url', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.drop_column('og_image_url')
