"""slug registry + public branch identity (slug, landing_enabled, is_active)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-02 23:45:00.000000

Phase 1 / Giai đoạn A of the hierarchical landing-page plan
(see KE_HOACH_LANDING_PHASE1.md). Schema only — no business-data merge here,
so this stays cheap to roll back with `alembic downgrade`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# System paths that must never be handed out as a tenant slug. Reserving wide
# up front is cheap; reclaiming a slug a customer already prints on signage is
# not. Includes marketing routes we may add later (/pricing, /about, ...).
RESERVED_SLUGS = [
    "admin", "api", "app", "auth", "assets", "static", "public", "uploads",
    "media", "book", "chat", "login", "logout", "register", "signup", "signin",
    "dashboard", "settings", "account", "profile", "platform", "org", "clinic",
    "branch", "health", "healthz", "status", "docs", "openapi", "swagger",
    "redoc", "graphql", "ws", "webhooks", "search", "help", "support",
    "pricing", "about", "contact", "privacy", "terms", "blog", "news",
    "robots.txt", "favicon.ico", "sitemap.xml", "manifest.json",
]


def upgrade() -> None:
    # ---- 1. Global slug namespace -------------------------------------------------
    op.create_table(
        'slug_registry',
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('slug'),
    )
    with op.batch_alter_table('slug_registry', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_slug_registry_entity_type'), ['entity_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_slug_registry_entity_id'), ['entity_id'], unique=False)
        # Resolving "current slug of entity X" is the hot path for building links.
        batch_op.create_index('ix_slug_registry_entity', ['entity_type', 'entity_id', 'is_active'], unique=False)

    # ---- 2. Public identity for branches ------------------------------------------
    with op.batch_alter_table('branches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('landing_enabled', sa.Boolean(), nullable=False,
                                      server_default=sa.text('0')))
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False,
                                      server_default=sa.text('1')))
        batch_op.create_index(batch_op.f('ix_branches_slug'), ['slug'], unique=True)

    # ---- 3. Landing toggles --------------------------------------------------------
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.add_column(sa.Column('landing_enabled', sa.Boolean(), nullable=False,
                                      server_default=sa.text('1')))
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('landing_enabled', sa.Boolean(), nullable=False,
                                      server_default=sa.text('1')))

    # ---- 4. Backfill ----------------------------------------------------------------
    _backfill()


def _backfill() -> None:
    """Give every existing branch a slug and load the registry.

    Uses the app's slugify (a pure string function) so generated slugs match
    what the running app would produce.
    """
    from backend.app.core.slug import slugify
    import secrets

    conn = op.get_bind()

    taken: set[str] = set()

    def claim(base: str, fallback: str) -> str:
        """First-come-first-served readable slug, random suffix only on collision."""
        candidate = slugify(base) or fallback
        if candidate not in taken and candidate not in RESERVED_SLUGS:
            taken.add(candidate)
            return candidate
        while True:
            candidate = f"{slugify(base) or fallback}-{secrets.token_hex(3)}"
            if candidate not in taken:
                taken.add(candidate)
                return candidate

    rows: list[tuple[str, str, int]] = []  # (slug, entity_type, entity_id)

    # Existing org/clinic slugs are already public - adopt them verbatim so no
    # live URL changes. They were generated with a random suffix already.
    for entity_type, table in (("organization", "organizations"), ("clinic", "clinics")):
        for eid, slug in conn.execute(sa.text(f"SELECT id, slug FROM {table}")).fetchall():
            if slug:
                taken.add(slug)
                rows.append((slug, entity_type, eid))

    # Branches have no slug yet -> generate readable ones.
    for bid, name in conn.execute(sa.text("SELECT id, name FROM branches ORDER BY id")).fetchall():
        slug = claim(name or f"co-so-{bid}", f"co-so-{bid}")
        conn.execute(sa.text("UPDATE branches SET slug = :s WHERE id = :i"), {"s": slug, "i": bid})
        rows.append((slug, "branch", bid))

    # Any org/clinic that somehow had no slug: leave it to the app's normal
    # slug assignment rather than inventing one blindly here.

    for slug, entity_type, entity_id in rows:
        conn.execute(
            sa.text("INSERT INTO slug_registry (slug, entity_type, entity_id, is_active) "
                    "VALUES (:s, :t, :i, 1)"),
            {"s": slug, "t": entity_type, "i": entity_id},
        )

    for word in RESERVED_SLUGS:
        if word in taken:
            continue  # a live tenant already owns it; don't break their URL
        conn.execute(
            sa.text("INSERT INTO slug_registry (slug, entity_type, entity_id, is_active) "
                    "VALUES (:s, 'reserved', NULL, 1)"),
            {"s": word},
        )


def downgrade() -> None:
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_column('landing_enabled')
    with op.batch_alter_table('clinics', schema=None) as batch_op:
        batch_op.drop_column('landing_enabled')
    with op.batch_alter_table('branches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_branches_slug'))
        batch_op.drop_column('is_active')
        batch_op.drop_column('landing_enabled')
        batch_op.drop_column('slug')
    with op.batch_alter_table('slug_registry', schema=None) as batch_op:
        batch_op.drop_index('ix_slug_registry_entity')
        batch_op.drop_index(batch_op.f('ix_slug_registry_entity_id'))
        batch_op.drop_index(batch_op.f('ix_slug_registry_entity_type'))
    op.drop_table('slug_registry')
