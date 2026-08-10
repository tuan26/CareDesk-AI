"""Feature flags, so features can be switched off without being deleted.

The first release deliberately sells one thing — more bookings and fewer
no-shows for a single da liễu/thẩm mỹ clinic — and several finished features
widen that promise without strengthening it. They are switched off here rather
than removed: the code and its tests stay, and turning any of them back on is a
flag flip instead of a rebuild.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feature_flags',
        sa.Column('id', sa.Integer(), nullable=False),
        # NULL = the vendor-wide default; a clinic_id overrides it for that clinic.
        sa.Column('clinic_id', sa.Integer(), nullable=True),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clinic_id', 'key', name='uq_feature_flag_scope'),
    )
    op.create_index('ix_feature_flags_clinic_id', 'feature_flags', ['clinic_id'])
    op.create_index('ix_feature_flags_key', 'feature_flags', ['key'])

    # The two most spam-prone automations start switched off on clinics that
    # already exist, matching what new clinics now get seeded with. Sending the
    # whole back catalogue a win-back message on the day the clinic goes live is
    # the fastest route to a spam complaint against a new Zalo OA.
    op.get_bind().execute(sa.text(
        "UPDATE automation_rules SET enabled = 0 "
        "WHERE is_system = 1 AND name IN ("
        "  'Đánh thức khách cũ (6 tháng)',"
        "  'Follow-up khách hỏi giá (5 ngày - ưu đãi)'"
        ")"
    ))


def downgrade() -> None:
    op.drop_index('ix_feature_flags_key', table_name='feature_flags')
    op.drop_index('ix_feature_flags_clinic_id', table_name='feature_flags')
    op.drop_table('feature_flags')
