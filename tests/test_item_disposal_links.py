import unittest
from types import SimpleNamespace

import models
from admin_routes import update_archived_item_disposal
from fastapi import HTTPException


class FakeQuery:
    def __init__(self, result=None, all_result=None):
        self.result = result
        self.all_result = [] if all_result is None else all_result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result

    def all(self):
        return self.all_result


class FakeSession:
    def __init__(self, *queries):
        self.queries = list(queries)
        self.committed = False
        self.rolled_back = False
        self.added = []

    def query(self, *args, **kwargs):
        return self.queries.pop(0)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def item(item_id, status, matched_item_id=None):
    return SimpleNamespace(
        id=item_id,
        status=status,
        archived=False,
        deleted=False,
        disposal_status="active",
        disposal_note=None,
        disposal_updated_at=None,
        is_matched=True,
        matched_item_id=matched_item_id,
        category="Electronics",
        brand=None,
        description=None,
        color=None,
        date=None,
        location=None,
        time_found=None,
        report_owner_name=None,
        image_path=None,
    )


class ItemDisposalLinkTests(unittest.TestCase):
    def test_scheduling_matched_found_item_moves_connected_lost_item(self):
        found = item(10, "found", matched_item_id=20)
        lost = item(20, "lost")
        claim = SimpleNamespace(
            found_item_id=10,
            lost_item_id=20,
            status="pending",
            admin_decision_date=None,
        )
        db = FakeSession(
            FakeQuery(result=found),
            FakeQuery(all_result=[claim]),
            FakeQuery(all_result=[]),
            FakeQuery(all_result=[lost]),
        )

        result = update_archived_item_disposal(
            10,
            {"action": "schedule", "note": "Unclaimed after holding period"},
            db=db,
            current_admin=SimpleNamespace(id=1),
        )

        self.assertTrue(db.committed)
        self.assertEqual(result["affected_item_count"], 2)
        self.assertEqual(result["cancelled_claim_count"], 1)
        self.assertEqual(claim.status, "rejected")
        for affected_item in (found, lost):
            self.assertTrue(affected_item.archived)
            self.assertFalse(affected_item.deleted)
            self.assertFalse(affected_item.is_matched)
            self.assertIsNone(affected_item.matched_item_id)
            self.assertEqual(affected_item.disposal_status, "for_disposal")
            self.assertEqual(affected_item.disposal_note, "Unclaimed after holding period")

    def test_claimed_pair_cannot_be_moved_to_disposal(self):
        found = item(10, "found", matched_item_id=20)
        claim = SimpleNamespace(
            found_item_id=10,
            lost_item_id=20,
            status=models.CLAIMED_CLAIM_STATUSES[0],
        )
        db = FakeSession(
            FakeQuery(result=found),
            FakeQuery(all_result=[claim]),
        )

        with self.assertRaises(HTTPException) as error:
            update_archived_item_disposal(
                10,
                {"action": "schedule"},
                db=db,
                current_admin=SimpleNamespace(id=1),
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(db.committed)


if __name__ == "__main__":
    unittest.main()
