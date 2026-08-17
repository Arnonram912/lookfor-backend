import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from main import analyze_lost_item_matches


class FakeQuery:
    def __init__(self, item):
        self.item = item

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.item


class FakeSession:
    def __init__(self, item):
        self.item = item
        self.committed = False

    def query(self, *args, **kwargs):
        return FakeQuery(self.item)

    def commit(self):
        self.committed = True


def lost_item(owner_id=7):
    return SimpleNamespace(
        id=7162,
        status="lost",
        user_id=owner_id,
        report_owner_user_id=None,
        report_owner_name=None,
        possible_matches='[{"id": 20, "score": 0.81}]',
    )


def user(user_id=7, is_admin=False):
    return SimpleNamespace(
        id=user_id,
        is_admin=is_admin,
        full_name="Test User",
        first_name=None,
        middle_name=None,
        last_name=None,
    )


class AnalyzeMatchesEndpointTests(unittest.TestCase):
    @patch("main.analyze_saved_item_details")
    def test_owner_reads_cached_matches_without_reanalysis(self, analyzer):
        db = FakeSession(lost_item())

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        self.assertEqual(result["matched_items"][0]["id"], 20)
        self.assertFalse(db.committed)
        analyzer.assert_not_called()

    def test_unrelated_student_cannot_reanalyze(self):
        db = FakeSession(lost_item(owner_id=7))

        with self.assertRaises(HTTPException) as raised:
            analyze_lost_item_matches(7162, db=db, current_user=user(user_id=8))

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
