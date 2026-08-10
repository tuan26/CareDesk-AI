"""Back up and restore the CareDesk database.

Works against whatever DATABASE_URL points at, so the same command runs on a
developer's SQLite file and on the production Postgres.

    python -m scripts.backup dump                 # write a timestamped backup
    python -m scripts.backup list
    python -m scripts.backup restore <file>       # into DATABASE_URL
    python -m scripts.backup drill                # dump -> restore -> verify

`drill` is the one that matters. A backup nobody has ever restored is not a
backup: the usual failures — pg_restore missing, wrong credentials, a dump that
was silently truncated — all look exactly like success until the day you need
it. Run it before the first real patient record exists, and again whenever the
hosting changes.
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Windows consoles often run a legacy codepage (cp932/cp1252) that cannot encode
# Vietnamese. Without this the script dies on its first print — after having
# done the work — which reads as a failed backup.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from backend.app.core.config import settings  # noqa: E402

BACKUP_DIR = REPO_ROOT / "backups"
# Tables whose row counts are compared before and after a restore. Patient data
# first: an "empty but valid" restore passes every other check.
VERIFY_TABLES = ["clinics", "users", "patient_leads", "appointments",
                 "services", "doctors", "working_schedules", "revenue_records"]


def _is_sqlite() -> bool:
    return settings.DATABASE_URL.startswith("sqlite")


def _sqlite_path() -> Path:
    return Path(settings.DATABASE_URL.replace("sqlite:///", ""))


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _counts() -> dict:
    """Row counts per table, used to prove a restore actually restored."""
    from sqlalchemy import create_engine, text

    engine = create_engine(settings.DATABASE_URL)
    out = {}
    with engine.connect() as conn:
        for table in VERIFY_TABLES:
            try:
                out[table] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            except Exception:
                out[table] = None      # table not in this schema version
    engine.dispose()
    return out


def dump(label: str = "") -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    suffix = f"_{label}" if label else ""

    if _is_sqlite():
        target = BACKUP_DIR / f"caredesk_{_stamp()}{suffix}.db"
        src = _sqlite_path()
        if not src.exists():
            raise SystemExit(f"Không tìm thấy database: {src}")
        # sqlite3's own backup API, not a file copy: copying a live database
        # mid-write produces a file that opens fine and is subtly corrupt.
        import sqlite3
        with sqlite3.connect(src) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
    else:
        target = BACKUP_DIR / f"caredesk_{_stamp()}{suffix}.dump"
        if not shutil.which("pg_dump"):
            raise SystemExit("Không tìm thấy pg_dump. Cài postgresql-client trước.")
        # Custom format (-Fc): compressed, and restorable table-by-table.
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--file", str(target),
             settings.DATABASE_URL],
            check=True,
        )

    size = target.stat().st_size
    if size < 1024:
        raise SystemExit(f"Bản sao lưu chỉ {size} byte — gần chắc chắn là hỏng.")
    print(f"✔ Đã sao lưu: {target}  ({size / 1024:.0f} KB)")
    return target


def restore(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Không tìm thấy file: {path}")

    if _is_sqlite():
        dest = _sqlite_path()
        if dest.exists():
            # Never overwrite the only copy of the current state, even during a
            # restore that is expected to succeed.
            safety = dest.with_suffix(f".before_restore_{_stamp()}")
            shutil.copy2(dest, safety)
            print(f"  (đã giữ lại bản hiện tại: {safety.name})")
        shutil.copy2(path, dest)
    else:
        if not shutil.which("pg_restore"):
            raise SystemExit("Không tìm thấy pg_restore. Cài postgresql-client trước.")
        subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner",
             "--dbname", settings.DATABASE_URL, str(path)],
            check=True,
        )
    print(f"✔ Đã phục hồi từ: {path}")


def list_backups() -> None:
    if not BACKUP_DIR.exists():
        print("Chưa có bản sao lưu nào.")
        return
    files = sorted(BACKUP_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        when = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        print(f"  {when}  {f.stat().st_size / 1024:>8.0f} KB  {f.name}")


def drill() -> None:
    """Dump, restore that dump, and prove the data survived.

    Deliberately restores over the live database: a drill against a copy proves
    the copy works, not that the real restore path does.
    """
    target = urlparse(settings.DATABASE_URL).path or settings.DATABASE_URL
    print(f"Diễn tập phục hồi trên: {target}")
    if os.getenv("ENVIRONMENT") == "production" and not os.getenv("I_MEAN_IT"):
        raise SystemExit(
            "Đây là production. Diễn tập sẽ ghi đè dữ liệu hiện tại. "
            "Chạy trên staging, hoặc đặt I_MEAN_IT=1 nếu bạn thực sự muốn."
        )

    before = _counts()
    print("  Trước:", {k: v for k, v in before.items() if v})

    path = dump(label="drill")
    restore(path)

    after = _counts()
    print("  Sau:  ", {k: v for k, v in after.items() if v})

    mismatched = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    if mismatched:
        raise SystemExit(f"✘ DIỄN TẬP THẤT BẠI — số dòng lệch: {mismatched}")

    if not any(before.values()):
        print("⚠ Database rỗng: diễn tập chạy xong nhưng chưa chứng minh được gì. "
              "Chạy lại trên bản sao có dữ liệu thật.")
        return

    print("✔ DIỄN TẬP ĐẠT — sao lưu và phục hồi đều hoạt động, số dòng khớp.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dump")
    sub.add_parser("list")
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("file")
    sub.add_parser("drill")

    args = parser.parse_args()
    if args.cmd == "dump":
        dump()
    elif args.cmd == "list":
        list_backups()
    elif args.cmd == "restore":
        restore(Path(args.file))
    elif args.cmd == "drill":
        drill()


if __name__ == "__main__":
    main()
