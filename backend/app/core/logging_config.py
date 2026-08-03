import logging
import sys


def setup_logging() -> None:
    """(Re-)configure root logging to INFO on stdout.

    Idempotent by design (force=True) because Alembic's env.py calls
    `fileConfig(alembic.ini)` during migrations, which resets the root
    logger's level/handlers to the ini's `[logger_root]` section (WARN,
    stderr). Left alone, every INFO/WARNING log after a migration run -
    including the one-time generated platform-admin password - would be
    silently dropped. Call this again right after run_migrations().
    """
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
