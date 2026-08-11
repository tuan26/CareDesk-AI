"""Doctor leave, and directions to a branch.

Two gaps found auditing the modules against what a clinic actually needs.

Leave is the dangerous one. WorkingSchedule says which weekdays a doctor works
and is true forever once entered, so with no way to record an exception the AI
books straight through Tết and the patient arrives at a locked door. That is the
kind of incident that gets the assistant switched off permanently, so it is
treated as a booking-correctness bug rather than a feature.

Directions are the small one: patients want a tap that opens their map app, and
a street address is not that.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'doctor_time_off',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        # NULL = the whole clinic is closed. A public holiday is entered once
        # rather than once per doctor, so nobody is forgotten.
        sa.Column('doctor_id', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        # Both NULL = the whole day; set both for a half day.
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('end_time', sa.Time(), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_doctor_time_off_clinic_id', 'doctor_time_off', ['clinic_id'])
    op.create_index('ix_doctor_time_off_doctor_id', 'doctor_time_off', ['doctor_id'])
    # The hot query is "anything covering this date?" on every slot lookup.
    op.create_index('ix_doctor_time_off_range', 'doctor_time_off',
                    ['start_date', 'end_date'])

    op.add_column('branches', sa.Column('map_url', sa.String(), nullable=True))
    op.add_column('branches', sa.Column('latitude', sa.Float(), nullable=True))
    op.add_column('branches', sa.Column('longitude', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('branches', 'longitude')
    op.drop_column('branches', 'latitude')
    op.drop_column('branches', 'map_url')
    op.drop_index('ix_doctor_time_off_range', table_name='doctor_time_off')
    op.drop_index('ix_doctor_time_off_doctor_id', table_name='doctor_time_off')
    op.drop_index('ix_doctor_time_off_clinic_id', table_name='doctor_time_off')
    op.drop_table('doctor_time_off')
