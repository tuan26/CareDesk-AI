#!/usr/bin/env bash
#
# Migration safety check. Run before every deploy, and before the pilot.
#
# Checks the three things that only bite in production: that a brand-new
# clinic's database can be built from nothing, that the schema Alembic
# produces still matches the models, and that the rollback actually works.
# The third is the one worth rehearsing — it found a downgrade that failed
# halfway on SQLite, leaving a half-dropped table, which is precisely the
# state you cannot afford to discover while trying to undo a bad deploy.
#
# Usage:  bash scripts/check_migrations.sh
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/Scripts/python.exe}"
# Repo-local on purpose: a temp path that works in git-bash, cmd and CI
# without a portable-path dance. Removed at both ends.
DB=".migcheck.db"
rm -f "$DB"
export DATABASE_URL="sqlite:///$DB"

echo "=== 1. DB trắng -> head (đường đi của phòng khám pilot mới) ==="
PYTHONIOENCODING=utf-8 $PY -c "
from backend.app.core.migrate import run_migrations
run_migrations(); print('OK')" 2>&1 | grep -E "OK|ERROR|Error" | tail -2

echo
echo "=== 2. Schema khớp model chưa (phát hiện drift) ==="
PYTHONIOENCODING=utf-8 $PY -c "
import sqlalchemy as sa
from backend.app.core.database import Base, engine
from backend.app.models import models  # noqa
insp = sa.inspect(engine)
have = set(insp.get_table_names())
missing_tables = [t for t in Base.metadata.tables if t not in have]
drift = []
for name, table in Base.metadata.tables.items():
    if name not in have: continue
    cols = {c['name'] for c in insp.get_columns(name)}
    for col in table.columns:
        if col.name not in cols:
            drift.append(f'{name}.{col.name}')
print('bảng thiếu :', missing_tables or 'không')
print('cột thiếu  :', drift or 'không')
assert not missing_tables and not drift, 'SCHEMA DRIFT'
print('OK — schema khớp model')"

echo
echo "=== 3. Rollback 3 revision mới rồi tiến lại (đường thoát khi pilot hỏng) ==="
PYTHONIOENCODING=utf-8 $PY -c "
from alembic import command
from alembic.config import Config
from pathlib import Path
cfg = Config(str(Path('backend/alembic.ini')))
cfg.set_main_option('script_location', 'backend/alembic')
command.downgrade(cfg, '-3')
print('  downgrade -3 OK')
command.upgrade(cfg, 'head')
print('  upgrade head OK')" 2>&1 | grep -E "OK|Error" | tail -4

echo
echo "=== 4. Chạy lại upgrade khi đã ở head (idempotent) ==="
PYTHONIOENCODING=utf-8 $PY -c "
from backend.app.core.migrate import run_migrations
run_migrations(); print('OK — chạy lại không lỗi')" 2>&1 | grep -E "OK|Error" | tail -1

rm -f "$DB"
