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

    @patch("main.release_stale_ai_match_after_reanalysis", return_value=1)
    @patch("main.analyze_saved_item_details")
    def test_no_new_match_releases_previous_unverified_ai_link(self, analyzer, release_match):
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

        release_match.assert_called_once_with(db, lost)
        self.assertTrue(result["match_released"])
        self.assertEqual(result["released_ai_links"], 1)
        self.assertFalse(result["auto_linked"])
        self.assertTrue(db.committed)

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

    @patch("main.replace_weaker_ai_match_after_reanalysis", return_value=0)
    @patch("main.analyze_saved_item_details")
    def test_reanalysis_repairs_stale_matched_flags_when_no_active_claim_exists(self, analyzer, _replace):
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
        self.assertEqual(len(claims), 1)
        self.assertTrue(lost.is_matched)
        self.assertTrue(found.is_matched)

    @patch("main.analyze_saved_item_details")
    def test_ranked_candidate_with_stale_matched_flag_is_linked(self, analyzer):
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
        self.assertTrue(result["auto_linked"])
        self.assertEqual(result["matched_item"]["id"], 7212)
        self.assertTrue(result["matched_item"]["available_for_match"])
        self.assertEqual(len(claims), 1)
        self.assertTrue(lost.is_matched)
        self.assertTrue(found.is_matched)

    @patch("main.replace_weaker_ai_match_after_reanalysis", return_value=1)
    @patch("main.analyze_saved_item_details")
    def test_stronger_match_replaces_previous_ai_link(self, analyzer, replace_match):
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
        self.assertTrue(result["match_replaced"])
        self.assertEqual(result["released_ai_links"], 1)
        self.assertEqual(result["claim_id"], 91)
        replace_match.assert_called_once()

    @patch("main.analyze_saved_item_details")
    def test_pending_found_match_is_reserved_without_creating_claim(self, analyzer):
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
        self.assertIsNone(result["claim_id"])
        self.assertEqual(pending.matched_item_id, lost.id)
        self.assertTrue(lost.is_matched)
        self.assertEqual(claims, [])
        self.assertTrue(db.committed)


if __name__ == "__main__":
    unittest.main()
