"""The visit itself: a queue, a record of what happened, and whether they return.

Three changes that close the gap between "đặt lịch" and "chăm sóc lại".

Retention baseline. The old returning-patient figure was a running total of
everyone who had ever come twice — it only ever went up, so it could never show
a change and could never justify the subscription. It is replaced by a cohort
rate (services/retention.py), which needs a "before" number the clinic states at
onboarding, because nobody can recall it two months later.

Queue timestamps are columns rather than new status values on purpose: status
already drives slot occupancy, revenue and reminders, so adding "arrived" and
"in_progress" there would ripple through all three for no gain. The queue state
is derived from arrived_at/started_at instead.

Visit records are deliberately not an EMR. No prescriptions: Vietnam has
specific rules for electronic prescriptions and a half-built one is a legal risk
the clinic carries while blaming us. Photos matter more here anyway — for
dermatology and aesthetics the before/after pair is both the clinical record and
the strongest sales asset the clinic owns.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clinics', sa.Column('baseline_return_percent', sa.Float(), nullable=True))

    op.add_column('appointments', sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('appointments', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'visit_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        # One record per visit, enforced: two records for one appointment would
        # mean two different accounts of what was done.
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=True),
        sa.Column('chief_complaint', sa.Text(), nullable=True),
        sa.Column('findings', sa.Text(), nullable=True),
        sa.Column('treatment_done', sa.Text(), nullable=True),
        sa.Column('advice', sa.Text(), nullable=True),
        sa.Column('next_visit_days', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_id'], ['patient_leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id', name='uq_visit_record_appointment'),
    )
    op.create_index('ix_visit_records_clinic_id', 'visit_records', ['clinic_id'])
    op.create_index('ix_visit_records_patient_id', 'visit_records', ['patient_id'])

    op.create_table(
        'visit_photos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('visit_record_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False, server_default='after'),
        # Unguessable, and unique so one upload can never overwrite another.
        # These are photographs of patients; the path must not be derivable from
        # a patient id or a counter.
        sa.Column('stored_name', sa.String(), nullable=False),
        sa.Column('original_name', sa.String(), nullable=True),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('caption', sa.String(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['visit_record_id'], ['visit_records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stored_name', name='uq_visit_photo_stored_name'),
    )
    op.create_index('ix_visit_photos_clinic_id', 'visit_photos', ['clinic_id'])
    op.create_index('ix_visit_photos_visit_record_id', 'visit_photos', ['visit_record_id'])


def downgrade() -> None:
    op.drop_index('ix_visit_photos_visit_record_id', table_name='visit_photos')
    op.drop_index('ix_visit_photos_clinic_id', table_name='visit_photos')
    op.drop_table('visit_photos')
    op.drop_index('ix_visit_records_patient_id', table_name='visit_records')
    op.drop_index('ix_visit_records_clinic_id', table_name='visit_records')
    op.drop_table('visit_records')
    op.drop_column('appointments', 'started_at')
    op.drop_column('appointments', 'arrived_at')
    op.drop_column('clinics', 'baseline_return_percent')
