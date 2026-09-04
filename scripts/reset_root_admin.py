"""Create or reset the root administrator account.

Run without --apply to preview the current root admin row. Run with --apply to
set the root admin password back to the project default and restore access.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from passlib.context import CryptContext
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database import engine
from lookfor_permissions import ADMIN_PERMISSION_KEYS, normalize_permissions


ROOT_ADMIN_EMAIL = "admin@novaliches.sti.edu.ph"
ROOT_ADMIN_NAME = "LookForAdministrator"
DEFAULT_ROOT_ADMIN_PASSWORD = "STI_Admin_2026"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def fetch_root_admin(connection):
    return connection.execute(
        text(
            """
            SELECT id, email, full_name, is_admin, is_archived, must_change_password
            FROM users
            WHERE LOWER(email) = :email
            """
        ),
        {"email": ROOT_ADMIN_EMAIL},
    ).mappings().first()


def reset_root_admin(connection) -> str:
    hashed_password = pwd_context.hash(DEFAULT_ROOT_ADMIN_PASSWORD)
    permissions = json.dumps(normalize_permissions(ADMIN_PERMISSION_KEYS))
    root_admin = fetch_root_admin(connection)

    if root_admin:
        connection.execute(
            text(
                """
                UPDATE users
                SET
                    full_name = :full_name,
                    hashed_password = :hashed_password,
                    is_admin = 1,
                    is_archived = 0,
                    must_change_password = 0,
                    permissions = :permissions
                WHERE LOWER(email) = :email
                """
            ),
            {
                "email": ROOT_ADMIN_EMAIL,
                "full_name": ROOT_ADMIN_NAME,
                "hashed_password": hashed_password,
                "permissions": permissions,
            },
        )
        return "updated"

    connection.execute(
        text(
            """
            INSERT INTO users (
                email,
                full_name,
                hashed_password,
                is_admin,
                is_archived,
                must_change_password,
                permissions
            )
            VALUES (
                :email,
                :full_name,
                :hashed_password,
                1,
                0,
                0,
                :permissions
            )
            """
        ),
        {
            "email": ROOT_ADMIN_EMAIL,
            "full_name": ROOT_ADMIN_NAME,
            "hashed_password": hashed_password,
            "permissions": permissions,
        },
    )
    return "created"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="reset the root admin account")
    args = parser.parse_args()

    with engine.begin() as connection:
        before = fetch_root_admin(connection)
        print("Root admin before:", dict(before) if before else None)

        if not args.apply:
            print("Dry run only. Re-run with --apply to reset the root admin password.")
            return

        result = reset_root_admin(connection)
        after = fetch_root_admin(connection)
        print(f"Root admin {result}.")
        print("Root admin after:", dict(after) if after else None)


if __name__ == "__main__":
    main()
