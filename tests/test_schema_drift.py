"""Every server_default in the models must exist in the database too.

booking_requests.created_at was declared server_default=func.now() on the model
but created as a plain nullable column by its migration. SQLAlchemy sends no
value for a server-default column — it expects the database to supply one — so
every row was written NULL, BookingRequestOut then failed to validate, and
GET /api/v1/booking-requests answered 500. Bookings were being recorded and were
invisible to the staff who had to act on them.

The class of bug matters more than the instance: a model and its migration
drifting apart is invisible until the exact code path that depends on it runs.
This test compares the two directly.
"""
import pytest
from sqlalchemy import create_engine, inspect

from backend.app.core.database import Base
from backend.app.models import models  # noqa: F401 — registers every table


@pytest.fixture(scope="module")
def live_columns():
    """Columns as the migrations actually build them."""
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    import tempfile

    from backend.app.core.config import settings

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp).as_posix()}/drift.db"
        cfg = Config(str(root / "backend" / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "backend" / "alembic"))

        # alembic/env.py overwrites sqlalchemy.url from settings, so setting it
        # on the Config alone would silently migrate the developer's real
        # database instead of this throwaway one.
        original = settings.DATABASE_URL
        settings.DATABASE_URL = url
        try:
            command.upgrade(cfg, "head")
        finally:
            settings.DATABASE_URL = original

        engine = create_engine(url)
        inspector = inspect(engine)
        out = {
            table: {c["name"]: c for c in inspector.get_columns(table)}
            for table in inspector.get_table_names()
        }
        engine.dispose()
        return out


def _model_server_defaults():
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.server_default is not None:
                yield table.name, column.name


def test_every_model_server_default_exists_in_the_database(live_columns):
    missing = []
    for table, column in _model_server_defaults():
        actual = live_columns.get(table, {}).get(column)
        if actual is None:
            missing.append(f"{table}.{column} (cột không tồn tại)")
        elif actual.get("default") is None:
            missing.append(f"{table}.{column} (migration thiếu DEFAULT)")

    assert not missing, (
        "Model khai server_default nhưng database không có — mọi dòng mới sẽ là "
        "NULL: " + ", ".join(missing)
    )


def test_the_two_columns_that_caused_the_outage_are_fixed(live_columns):
    for table in ("booking_requests", "public_chat_sessions"):
        column = live_columns[table]["created_at"]
        assert column["default"] is not None, f"{table}.created_at vẫn thiếu DEFAULT"
        assert not column["nullable"], f"{table}.created_at vẫn cho phép NULL"


def test_every_model_table_exists_in_the_migrations(live_columns):
    """A model with no migration works in tests (create_all) and fails in
    production (alembic upgrade), which is the worst possible place to find out."""
    missing = [t.name for t in Base.metadata.sorted_tables if t.name not in live_columns]
    assert not missing, f"Bảng có trong model nhưng chưa có migration: {missing}"
