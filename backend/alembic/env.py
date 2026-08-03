from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from backend.app.core.config import settings
from backend.app.core.database import Base
from backend.app.models import models  # noqa: F401 - register all tables on Base.metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    # disable_existing_loggers=False: this runs inside the live app process
    # (backend.app.core.migrate.run_migrations), not just the standalone
    # `alembic` CLI. The default (True) tears down every logger the app
    # already configured. main.py re-applies its own logging config right
    # after migrations run, as a second safety net.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # render_as_batch: SQLite cannot ALTER constraints; batch mode uses copy-and-move
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
