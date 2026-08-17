import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

import models
from admin_routes import (
    BulkItemDeleteRequest,
    BulkItemDeleteTarget,
    bulk_move_items_to_deleted,
)


SCRIPT = Path(__file__).resolve().parents[1] / "static" / "admin-item-bulk-actions.js"


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, items=None, pending_items=None):
        self.items = items or []
        self.pending_items = pending_items or []
        self.commit_count = 0

    def query(self, model):
        return FakeQuery(self.pending_items if model is models.PendingItem else self.items)

    def commit(self):
        self.commit_count += 1


def admin(permission):
    return SimpleNamespace(
        id=9,
        is_admin=True,
        email="staff-admin@example.test",
        permissions=[permission],
    )


class AdminItemBulkDeleteTests(unittest.TestCase):
    def test_empty_bulk_delete_is_rejected_by_endpoint_validation(self):
        with self.assertRaises(HTTPException) as raised:
            bulk_move_items_to_deleted(
                BulkItemDeleteRequest(scope="found", items=[]),
                db=FakeSession(),
                current_admin=admin("found_items.delete"),
            )

        self.assertEqual(raised.exception.status_code, 400)

    def test_found_bulk_delete_updates_regular_and_pending_items_once(self):
        found_item = SimpleNamespace(id=1, status="found", archived=False, deleted=False)
        pending_item = SimpleNamespace(id=2, archived=False, deleted=False)
        db = FakeSession(items=[found_item], pending_items=[pending_item])
        payload = BulkItemDeleteRequest(
            scope="found",
            items=[
                BulkItemDeleteTarget(id=1, is_pending=False),
                BulkItemDeleteTarget(id=2, is_pending=True),
            ],
        )

        result = bulk_move_items_to_deleted(
            payload,
            db=db,
            current_admin=admin("found_items.delete"),
        )

        self.assertTrue(found_item.archived and found_item.deleted)
        self.assertTrue(pending_item.archived and pending_item.deleted)
        self.assertEqual(result["updated_count"], 2)
        self.assertEqual(db.commit_count, 1)

    def test_lost_bulk_delete_rejects_pending_found_targets(self):
        payload = BulkItemDeleteRequest(
            scope="lost",
            items=[BulkItemDeleteTarget(id=2, is_pending=True)],
        )

        with self.assertRaises(HTTPException) as raised:
            bulk_move_items_to_deleted(
                payload,
                db=FakeSession(),
                current_admin=admin("lost_items.delete"),
            )

        self.assertEqual(raised.exception.status_code, 400)

    def test_shared_bulk_script_uses_single_batch_delete_request(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("fetch('/admin/items/bulk-delete'", script)
        self.assertIn("items: items.map(item =>", script)
        self.assertIn("scope.selected.clear()", script)


if __name__ == "__main__":
    unittest.main()
