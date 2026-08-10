"""Onboarding state and the clinic's before-CareDesk numbers.

The baseline columns are the ones that matter commercially. The product is sold
as "more bookings, fewer no-shows" — both comparisons — and nobody remembers
what their no-show rate was two months ago. Asking on day one, and storing the
clinic's own answer, is the only way to have anything to show at renewal.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clinics', sa.Column('onboarding_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clinics', sa.Column('baseline_monthly_bookings', sa.Integer(), nullable=True))
    op.add_column('clinics', sa.Column('baseline_no_show_percent', sa.Float(), nullable=True))
    op.add_column('clinics', sa.Column('baseline_daily_price_asks', sa.Integer(), nullable=True))
    op.add_column('clinics', sa.Column('baseline_captured_at', sa.DateTime(timezone=True), nullable=True))

    # Clinics that already exist are live and working; do not send them back
    # through setup. Only new signups start with onboarding pending.
    op.get_bind().execute(sa.text(
        "UPDATE clinics SET onboarding_completed_at = CURRENT_TIMESTAMP "
        "WHERE onboarding_completed_at IS NULL"
    ))


def downgrade() -> None:
    op.drop_column('clinics', 'baseline_captured_at')
    op.drop_column('clinics', 'baseline_daily_price_asks')
    op.drop_column('clinics', 'baseline_no_show_percent')
    op.drop_column('clinics', 'baseline_monthly_bookings')
    op.drop_column('clinics', 'onboarding_completed_at')
