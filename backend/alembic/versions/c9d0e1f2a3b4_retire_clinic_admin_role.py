"""Retire the clinic-level "admin" role.

It was indistinguishable from "owner" in permissions — every RoleChecker that
accepted one accepted the other, and verify_admin was never attached to an
endpoint — but strictly worse in effect: reminder.py and tenant_stats.py both
look up ``role == "owner"``, so an "admin" silently received no 8h/20h
operations digest and showed as "—" in the platform console's owner column.

Two distinct populations carry the string today, and they must go different ways:

  * clinic staff  -> "owner"    (they already had owner's permissions; this only
                                 makes them visible to the digest)
  * the vendor    -> "platform" (its access comes from is_platform_admin, not
                                 from role; the rename just stops "admin" from
                                 looking like a clinic role)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Vendor first. is_platform_admin is a boolean column — SQLite stores 0/1,
    # Postgres true/false — so test it directly instead of comparing to 1.
    conn.execute(sa.text(
        "UPDATE users SET role = 'platform' "
        "WHERE role = 'admin' AND is_platform_admin"
    ))
    # Everything still on 'admin' is therefore clinic staff. Written as a
    # blanket update rather than "AND NOT is_platform_admin" so a NULL flag
    # cannot leave a row stranded on the retired role.
    conn.execute(sa.text("UPDATE users SET role = 'owner' WHERE role = 'admin'"))

    left = conn.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE role = 'admin'"
    )).scalar()
    assert left == 0, f"{left} user(s) still on the retired 'admin' role"


def downgrade() -> None:
    # Only the vendor account can be restored unambiguously: the staff accounts
    # that were folded into "owner" are no longer distinguishable from the ones
    # that were owners all along, and guessing would demote real owners.
    op.get_bind().execute(sa.text(
        "UPDATE users SET role = 'admin' WHERE role = 'platform'"
    ))
