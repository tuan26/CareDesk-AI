"""pilot readiness: revisit-interval review marker, and the detection verdict

Two columns the controlled pilot needs. The review marker lets a clinic finish
the revisit step honestly when nothing they do repeats, instead of inventing an
interval to escape it. The verdict records whether staff thought each detected
opportunity was worth chasing at all — the only way to tell a detector that
finds many misses from one that finds the right ones.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "revisit_intervals_reviewed_at" not in _columns("clinics"):
        op.add_column("clinics", sa.Column("revisit_intervals_reviewed_at",
                                           sa.DateTime(timezone=True), nullable=True))

    opportunity_columns = _columns("revenue_opportunities")
    if "is_real_opportunity" not in opportunity_columns:
        op.add_column("revenue_opportunities",
                      sa.Column("is_real_opportunity", sa.String(), nullable=True))
        op.create_index("ix_revenue_opportunities_is_real",
                        "revenue_opportunities", ["is_real_opportunity"])
    if "judged_at" not in opportunity_columns:
        op.add_column("revenue_opportunities",
                      sa.Column("judged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("revenue_opportunities", "judged_at")
    op.drop_index("ix_revenue_opportunities_is_real", table_name="revenue_opportunities")
    op.drop_column("revenue_opportunities", "is_real_opportunity")
    op.drop_column("clinics", "revisit_intervals_reviewed_at")
