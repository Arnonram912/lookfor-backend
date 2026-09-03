"""Back up and remove notification and audit-log records.

Users and all account-related data are preserved.
Run without --apply for counts only; use --apply to perform the deletion.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database import engine


TABLES = ("notifications", "audit_logs")


def count_rows(connection) -> dict[str, int]:
    return {
        table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        for table in TABLES
    }


def export_backup(connection) -> Path:
    backup_dir = PROJECT_ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    payload: dict[str, list[dict]] = {}
    for table in TABLES:
        rows = connection.execute(text(f"SELECT * FROM {table}")).mappings().all()
        payload[table] = [dict(row) for row in rows]

    path = backup_dir / f"notification-audit-logs-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    return path


def clear_records(connection) -> None:
    connection.execute(text("DELETE FROM notifications"))
    connection.execute(text("DELETE FROM audit_logs"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the permanent cleanup")
    args = parser.parse_args()

    with engine.begin() as connection:
        before = count_rows(connection)
        print("Before:", before)
        if not args.apply:
            print("Dry run only. Re-run with --apply to delete these records.")
            return
        backup_path = export_backup(connection)
        clear_records(connection)
        print("Backup:", backup_path)
        print("After:", count_rows(connection))


if __name__ == "__main__":
    main()