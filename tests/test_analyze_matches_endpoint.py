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
    @patch("main.synchronize_automatic_item_match", return_value=(False, False))
    @patch("main.analyze_saved_item_details")
    def test_owner_explicitly_reanalyzes_and_persists_result(self, analyzer, _sync):
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

    @patch("main.synchronize_automatic_item_match", return_value=(False, False))
    @patch("main.analyze_saved_item_details")
    def test_reanalysis_does_not_change_an_existing_match(self, analyzer, _sync):
        lost = lost_item()
        lost.is_matched = True
        db = FakeSession(lost)
        analyzer.return_value = {
            "highest_score": 0.0,
            "matched_item": None,
            "matched_items": [],
            "action": "no_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        self.assertFalse(result["match_released"])
        self.assertEqual(result["released_ai_links"], 0)
        self.assertFalse(result["auto_linked"])
        self.assertTrue(lost.is_matched)
        self.assertTrue(db.committed)

    def test_unrelated_student_cannot_reanalyze(self):
        db = FakeSession(lost_item(owner_id=7))

        with self.assertRaises(HTTPException) as raised:
            analyze_lost_item_matches(7162, db=db, current_user=user(user_id=8))

        self.assertEqual(raised.exception.status_code, 403)

    @patch("main.synchronize_automatic_item_match", return_value=(True, False))
    @patch("main.analyze_saved_item_details")
    def test_authoritative_score_requires_admin_selection(self, analyzer, _sync):
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
        self.assertIsNone(result["claim_id"])
        self.assertTrue(result["requires_admin_selection"])
        self.assertFalse(lost.is_matched)
        self.assertFalse(found.is_matched)
        self.assertEqual(claims, [])
        self.assertTrue(db.committed)

    @patch("main.synchronize_automatic_item_match", return_value=(True, False))
    @patch("main.analyze_saved_item_details")
    def test_reanalysis_does_not_create_claim_for_previously_matched_item(self, analyzer, _sync):
        lost = lost_item()
        lost.is_matched = True
        found = SimpleNamespace(id=7194, is_matched=True)
        db = SequencedFakeSession([lost, found, None, None])
        analyzer.return_value = {
            "highest_score": 0.796,
            "matched_item": {"id": 7194, "source": "found", "score": 0.796},
            "matched_items": [{"id": 7194, "source": "found", "score": 0.796}],
            "action": "show_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        claims = [value for value in db.added if isinstance(value, models.Claim)]
        self.assertTrue(result["auto_linked"])
        self.assertTrue(result["requires_admin_selection"])
        self.assertEqual(claims, [])
        self.assertTrue(lost.is_matched)
        self.assertTrue(found.is_matched)

    @patch("main.synchronize_automatic_item_match", return_value=(False, False))
    @patch("main.analyze_saved_item_details")
    def test_ranked_candidate_with_stale_flag_still_requires_admin_selection(self, analyzer, _sync):
        lost = lost_item()
        found = SimpleNamespace(id=7212, is_matched=True)
        # lost lookup, candidate ownership check, found lookup, existing pair,
        # and final conflicting-claim check.
        db = SequencedFakeSession([lost, None, found, None, None])
        analyzer.return_value = {
            "highest_score": 0.893,
            "matched_item": None,
            "matched_items": [
                {
                    "id": 7212,
                    "source": "found",
                    "score": 0.893,
                    "available_for_match": False,
                }
            ],
            "ranked_candidates": [
                {
                    "id": 7212,
                    "source": "found",
                    "score": 0.893,
                    "available_for_match": False,
                }
            ],
            "action": "show_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        claims = [value for value in db.added if isinstance(value, models.Claim)]
        self.assertFalse(result["auto_linked"])
        self.assertIsNone(result["matched_item"])
        self.assertTrue(result["requires_admin_selection"])
        self.assertEqual(claims, [])
        self.assertFalse(lost.is_matched)
        self.assertTrue(found.is_matched)

    @patch("main.synchronize_automatic_item_match", return_value=(False, False))
    @patch("main.analyze_saved_item_details")
    def test_occupied_top_candidate_does_not_fall_through_to_second_highest(
        self,
        analyzer,
        _sync,
    ):
        lost = lost_item()
        lost.is_matched = True
        top_candidate_owner = SimpleNamespace(lost_item_id=9001)
        db = SequencedFakeSession([lost, top_candidate_owner])
        analyzer.return_value = {
            "highest_score": 0.91,
            "matched_item": None,
            "matched_items": [
                {"id": 8001, "source": "found", "score": 0.91},
                {"id": 8002, "source": "found", "score": 0.86},
            ],
            "ranked_candidates": [
                {
                    "id": 8001,
                    "source": "found",
                    "score": 0.91,
                    "available_for_match": False,
                },
                {
                    "id": 8002,
                    "source": "found",
                    "score": 0.86,
                    "available_for_match": True,
                },
            ],
            "action": "show_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        self.assertFalse(result["auto_linked"])
        self.assertIsNone(result["matched_item"])
        self.assertEqual(result["released_ai_links"], 0)
        self.assertTrue(result["requires_admin_selection"])
        self.assertTrue(db.committed)

    @patch("main.synchronize_automatic_item_match", return_value=(True, False))
    @patch("main.analyze_saved_item_details")
    def test_stronger_match_does_not_replace_link_without_admin_selection(self, analyzer, _sync):
        lost = lost_item()
        lost.is_matched = True
        found = SimpleNamespace(id=7194, is_matched=False)
        db = SequencedFakeSession([lost, found, None, None])
        analyzer.return_value = {
            "highest_score": 0.86,
            "matched_item": {"id": 7194, "source": "found", "score": 0.86},
            "matched_items": [{"id": 7194, "source": "found", "score": 0.86}],
            "ranked_candidates": [
                {"id": 7194, "source": "found", "score": 0.86},
                {"id": 20, "source": "found", "score": 0.81},
            ],
            "action": "show_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        self.assertTrue(result["auto_linked"])
        self.assertFalse(result["match_replaced"])
        self.assertEqual(result["released_ai_links"], 0)
        self.assertIsNone(result["claim_id"])
        self.assertTrue(result["requires_admin_selection"])

    @patch("main.synchronize_automatic_item_match", return_value=(True, True))
    @patch("main.analyze_saved_item_details")
    def test_pending_found_match_is_not_reserved_or_claimed(self, analyzer, _sync):
        lost = lost_item()
        pending = SimpleNamespace(id=99, matched_item_id=None, archived=False, deleted=False)
        db = SequencedFakeSession([lost, pending, None, None])
        analyzer.return_value = {
            "highest_score": 0.84,
            "matched_item": {"id": 99, "source": "pending_found", "score": 0.84},
            "matched_items": [{"id": 99, "source": "pending_found", "score": 0.84}],
            "action": "show_match",
        }

        result = analyze_lost_item_matches(7162, db=db, current_user=user())

        claims = [value for value in db.added if isinstance(value, models.Claim)]
        self.assertTrue(result["auto_linked"])
        self.assertTrue(result["pending_approval"])
        self.assertTrue(result["requires_admin_selection"])
        self.assertIsNone(result["claim_id"])
        self.assertIsNone(pending.matched_item_id)
        self.assertFalse(lost.is_matched)
        self.assertEqual(claims, [])
        self.assertTrue(db.committed)


if __name__ == "__main__":
    unittest.main()
