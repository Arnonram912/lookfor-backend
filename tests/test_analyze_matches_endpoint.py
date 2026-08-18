import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from main import analyze_lost_item_matches
import models


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


class SequencedFakeSession(FakeSession):
    def __init__(self, query_results):
        super().__init__(query_results[0])
        self.query_results = list(query_results)
        self.added = []

    def query(self, *args, **kwargs):
        return FakeQuery(self.query_results.pop(0))

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if isinstance(value, models.Claim) and value.id is None:
                value.id = 91


def lost_item(owner_id=7):
    return SimpleNamespace(
        id=7162,
        status="lost",
        user_id=owner_id,
        report_owner_user_id=None,
        report_owner_name=None,
        possible_matches='[{"id": 20, "score": 0.81}]',
        archived=False,
        deleted=False,
        is_matched=False,
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
    def test_owner_explicitly_reanalyzes_and_persists_result(self, analyzer):
        db = FakeSession(lost_item())
        analyzer.return_value = {
            "highest_score": 0.0,
            "matched_item": None,
            "matched_items": [],
            "action": "no_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        self.assertEqual(result["matched_items"], [])
        self.assertFalse(result["auto_linked"])
        self.assertTrue(db.committed)
        analyzer.assert_called_once_with(db, db.item, record_type="item")

    def test_unrelated_student_cannot_reanalyze(self):
        db = FakeSession(lost_item(owner_id=7))

        with self.assertRaises(HTTPException) as raised:
            analyze_lost_item_matches(7162, db=db, current_user=user(user_id=8))

        self.assertEqual(raised.exception.status_code, 403)

    @patch("main.analyze_saved_item_details")
    def test_authoritative_score_links_both_items_and_creates_claim(self, analyzer):
        lost = lost_item()
        found = SimpleNamespace(id=7194, is_matched=False)
        db = SequencedFakeSession([lost, found, None, None])
        analyzer.return_value = {
            "highest_score": 0.82,
            "matched_item": {"id": 7194, "source": "found", "score": 0.82},
            "matched_items": [{"id": 7194, "source": "found", "score": 0.82}],
            "action": "show_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        claims = [value for value in db.added if isinstance(value, models.Claim)]
        self.assertTrue(result["auto_linked"])
        self.assertEqual(result["claim_id"], 91)
        self.assertTrue(lost.is_matched)
        self.assertTrue(found.is_matched)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].similarity_score, "82.0%")
        self.assertTrue(db.committed)


if __name__ == "__main__":
    unittest.main()
