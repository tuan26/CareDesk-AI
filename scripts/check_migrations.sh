#!/usr/bin/env bash
#
# Migration safety check. Run before every deploy, and before the pilot.
#
# Checks the four things that only bite in production: that a brand-new
# clinic's database can be built from nothing, that migrations also apply to a
# database that already has rows in it, that the schema still matches the
# models, and that the rollback works.
#
# The last two earned their place by failing. The rollback check found a
# downgrade that died halfway on SQLite, leaving a half-dropped table. The
# populated-database check exists because an earlier version of this script
# only ever migrated an empty one: SQLite accepts "ADD COLUMN ... NOT NULL"
# with no default on a table with no rows and rejects it on a table with any,
# so a broken migration passed here and failed on the first database that
# mattered. An empty database is not a rehearsal.
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
echo "=== 1b. DB CÓ DỮ LIỆU -> head (đường đi của phòng khám đang chạy) ==="
# SQLite chấp nhận ADD COLUMN NOT NULL trên bảng rỗng và từ chối trên bảng có
# dòng. Migration chỉ thử trên DB trắng là chưa thử gì cả.
PYTHONIOENCODING=utf-8 $PY -c "
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pathlib import Path
from backend.app.core.database import engine

cfg = Config(str(Path('backend/alembic.ini')))
cfg.set_main_option('script_location', 'backend/alembic')

# Lùi về gốc, dừng ở schema TRƯỚC các cột mới, rồi chèn dữ liệu bằng SQL thô —
# không dùng ORM, vì model đã biết các cột chưa tồn tại ở bước này.
command.downgrade(cfg, 'base')
command.upgrade(cfg, 'b3c4d5e6f7a8')
with engine.begin() as conn:
    conn.execute(sa.text(
        \"INSERT INTO clinics (name, is_active, monthly_fee) VALUES \"
        \"('Phong kham co san', 1, 0), ('Phong kham tra phi', 1, 3000000)\"))

command.upgrade(cfg, 'head')

with engine.begin() as conn:
    rows = conn.execute(sa.text('SELECT name, monthly_fee, pricing_mode FROM clinics')).all()
for name, fee, mode in rows:
    print(f'  {name:22} fee={fee:>10,.0f}  mode={mode}')
zero = {m for n, f, m in rows if not f}
paid = {m for n, f, m in rows if f}
assert zero == {'unconfigured'}, f'fee=0 bi doan thanh {zero} thay vi unconfigured'
assert paid == {'paid'}, f'fee>0 phai thanh paid, dang la {paid}'
print('OK — migrate duoc tren DB co du lieu, va fee=0 khong bi doan bua')" 2>&1 | grep -E "^  |OK|Error|assert" | tail -6

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
