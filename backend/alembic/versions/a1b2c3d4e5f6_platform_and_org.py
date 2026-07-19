"""platform super-admin and organization/chain

Revision ID: a1b2c3d4e5f6
Revises: 2eecfa6c8c19
Create Date: 2026-07-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '2eecfa6c8c19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Organizations (chains)
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_organizations_id'), ['id'], unique=False)

    # users: organization_id + is_platform_admin
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('is_platform_admin', sa.Boolean(), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_organization_id'), ['organization_id'], unique=False)
        batch_op.create_foreign_key('fk_users_organization_id', 'organizations',
                                    ['organization_id'], ['id'], ondelete='CASCADE')

    # clinics: organization_id + is_active
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=True))
        batch_op.create_index(batch_op.f('ix_clinics_organization_id'), ['organization_id'], unique=False)
        batch_op.create_foreign_key('fk_clinics_organization_id', 'organizations',
                                    ['organization_id'], ['id'], ondelete='SET NULL')

    # Backfill existing rows to sensible defaults
    op.execute("UPDATE users SET is_platform_admin = 0 WHERE is_platform_admin IS NULL")
    op.execute("UPDATE clinics SET is_active = 1 WHERE is_active IS NULL")


def downgrade() -> None:
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.drop_constraint('fk_clinics_organization_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_clinics_organization_id'))
        batch_op.drop_column('is_active')
        batch_op.drop_column('organization_id')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_organization_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_users_organization_id'))
        batch_op.drop_column('is_platform_admin')
        batch_op.drop_column('organization_id')

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organizations_id'))
    op.drop_table('organizations')
