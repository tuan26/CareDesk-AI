"""revenue attribution v1: actions, and the chain from opportunity to money

Adds the outreach log and the four columns that let an opportunity name the
booking and the revenue record it produced, so "recovered" stops meaning
"someone booked something afterwards".

Revision ID: a2b3c4d5e6f7
Revises: f9a0b1c2d3e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = (
    ("attribution_class", sa.String()),
    ("booked_at", sa.DateTime(timezone=True)),
    ("resolved_booking_request_id", sa.Integer()),
    ("resolved_revenue_record_id", sa.Integer()),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("revenue_opportunities")}

    for name, kind in _NEW_COLUMNS:
        if name not in existing:
            op.add_column("revenue_opportunities", sa.Column(name, kind, nullable=True))
    if "attribution_class" not in existing:
        op.create_index("ix_revenue_opportunities_attribution",
                        "revenue_opportunities", ["attribution_class"])

    if "revenue_actions" in set(inspector.get_table_names()):
        return

    op.create_table(
        "revenue_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clinic_id", sa.Integer(), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("template_code", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="sent"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["revenue_opportunities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revenue_actions_clinic_id", "revenue_actions", ["clinic_id"])
    op.create_index("ix_revenue_actions_opportunity_id", "revenue_actions", ["opportunity_id"])
    op.create_index("ix_revenue_actions_status", "revenue_actions", ["status"])

    # Opportunities already marked recovered were credited before any of this
    # existed: their amount may be an estimate rather than money, and a single
    # visit may have credited several of them. Reopening them would erase a
    # receptionist's work, so they are left alone and marked unknown, which
    # keeps them out of every attribution total.
    op.execute("""
        UPDATE revenue_opportunities
           SET attribution_class = 'unknown'
         WHERE status = 'recovered' AND attribution_class IS NULL
    """)


def downgrade() -> None:
    op.drop_table("revenue_actions")
    # The index has to go first. SQLite refuses to drop a column an index still
    # references, and it fails halfway through — leaving the table with some
    # columns gone and the migration marked unapplied. Found by rehearsing the
    # rollback rather than by needing it, which is the only good time to find it.
    op.drop_index("ix_revenue_opportunities_attribution", table_name="revenue_opportunities")
    for name, _ in _NEW_COLUMNS:
        op.drop_column("revenue_opportunities", name)
