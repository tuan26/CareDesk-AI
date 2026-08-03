import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

# backend/app/core/migrate.py -> backend/
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_migrations() -> None:
    """Bring the database schema up to the latest Alembic revision.

    Replaces the old `Base.metadata.create_all()` startup step, which only
    creates missing tables and silently leaves existing tables missing any
    column added since — the exact drift that broke seeding here (schema had
    no `clinics.default_locale`). Alembic is now the single source of truth
    for schema; env.py resolves the DB URL from settings.DATABASE_URL.
    """
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    logger.info("Applying database migrations (alembic upgrade head)...")
    command.upgrade(cfg, "head")
    logger.info("Database schema is up to date.")
