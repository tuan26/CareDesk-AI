"""plans catalogue + clinic/org slugs + trial

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('monthly_quota', sa.Integer(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('trial_days', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_plans_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_plans_code'), ['code'], unique=True)

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(), nullable=True))
        batch_op.create_index(batch_op.f('ix_organizations_slug'), ['slug'], unique=True)

    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('plan_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f('ix_clinics_slug'), ['slug'], unique=True)
        batch_op.create_foreign_key('fk_clinics_plan_id', 'plans', ['plan_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.drop_constraint('fk_clinics_plan_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_clinics_slug'))
        batch_op.drop_column('trial_ends_at')
        batch_op.drop_column('plan_id')
        batch_op.drop_column('slug')

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organizations_slug'))
        batch_op.drop_column('slug')

    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_plans_code'))
        batch_op.drop_index(batch_op.f('ix_plans_id'))
    op.drop_table('plans')
