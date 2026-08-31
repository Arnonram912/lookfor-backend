import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from item_match_lifecycle import (
    authorize_single_ai_link,
    delete_item_claims_and_release_matches,
    release_pending_found_link,
    release_stale_ai_match_after_reanalysis,
    replace_weaker_ai_match_after_reanalysis,
    remove_cached_possible_match,
    strongest_upload_match,
)


class ScriptedQuery:
    def __init__(self, *, all_value=None, first_value=None):
        self.all_value = [] if all_value is None else all_value
        self.first_value = first_value
        self.deleted = False

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.all_value

    def first(self):
        return self.first_value

    def delete(self, **kwargs):
        self.deleted = True


class ScriptedDB:
    def __init__(self, queries):
        self.queries = list(queries)
        self.flush_count = 0

    def query(self, *args, **kwargs):
        return self.queries.pop(0)

    def flush(self):
        self.flush_count += 1


class ItemMatchLifecycleTests(unittest.TestCase):
    def test_upload_can_consider_unavailable_candidate_for_safe_replacement(self):
        candidate = {
            "id": 18,
            "source": "found",
            "score": 0.89,
            "available_for_match": False,
        }

        selected = strongest_upload_match({"matched_item": None, "ranked_candidates": [candidate]})

        self.assertEqual(selected["id"], 18)
        self.assertTrue(selected["available_for_match"])

    @patch("item_match_lifecycle.replace_weaker_ai_match_after_reanalysis", return_value=2)
    def test_higher_upload_replaces_existing_ai_links(self, replace_match):
        lost = SimpleNamespace(
            id=18,
            status="lost",
            is_matched=True,
            possible_matches='[{"id": 22, "source": "pending_found", "score": 0.89}]',
        )
        old_claim = SimpleNamespace(found_item_id=16)
        db = ScriptedDB([
            ScriptedQuery(all_value=[old_claim]),
            ScriptedQuery(all_value=[]),
        ])

        authorized, released = authorize_single_ai_link(
            db,
            lost,
            {"id": 22, "source": "pending_found", "score": 0.89},
        )

        self.assertTrue(authorized)
        self.assertEqual(released, 2)
        replace_match.assert_called_once()

    @patch("item_match_lifecycle.replace_weaker_ai_match_after_reanalysis", return_value=0)
    def test_lower_upload_cannot_create_second_link(self, replace_match):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True, possible_matches=None)
        old_claim = SimpleNamespace(found_item_id=16)
        db = ScriptedDB([
            ScriptedQuery(all_value=[old_claim]),
            ScriptedQuery(all_value=[]),
        ])

        authorized, released = authorize_single_ai_link(
            db,
            lost,
            {"id": 22, "source": "pending_found", "score": 0.79},
        )

        self.assertFalse(authorized)
        self.assertEqual(released, 0)
        replace_match.assert_called_once()

    def test_remove_cached_possible_match_preserves_other_candidates(self):
        lost = SimpleNamespace(possible_matches=json.dumps([
            {"id": 11, "source": "found", "score": 0.9},
            {"id": 12, "source": "found", "score": 0.8},
        ]))

        removed = remove_cached_possible_match(lost, 11, source="found")

        self.assertTrue(removed)
        self.assertEqual(json.loads(lost.possible_matches), [
            {"id": 12, "source": "found", "score": 0.8}
        ])

    def test_deleting_lost_item_releases_its_found_counterpart(self):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True)
        found = SimpleNamespace(id=16, status="found", is_matched=True)
        claim = SimpleNamespace(id=30, lost_item_id=18, found_item_id=16)
        db = ScriptedDB([
            ScriptedQuery(all_value=[claim]),
            ScriptedQuery(all_value=[found]),
            ScriptedQuery(),
            ScriptedQuery(),
            ScriptedQuery(),
            ScriptedQuery(first_value=None),
        ])

        delete_item_claims_and_release_matches(db, lost)

        self.assertFalse(lost.is_matched)
        self.assertFalse(found.is_matched)
        self.assertEqual(db.flush_count, 1)

    def test_counterpart_stays_matched_when_another_active_claim_exists(self):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True)
        found = SimpleNamespace(id=16, status="found", is_matched=True)
        claim = SimpleNamespace(id=30, lost_item_id=18, found_item_id=16)
        db = ScriptedDB([
            ScriptedQuery(all_value=[claim]),
            ScriptedQuery(all_value=[found]),
            ScriptedQuery(),
            ScriptedQuery(),
            ScriptedQuery(),
            ScriptedQuery(first_value=(99,)),
        ])

        delete_item_claims_and_release_matches(db, lost)

        self.assertTrue(found.is_matched)

    def test_deleting_pending_found_releases_reserved_lost_item(self):
        lost = SimpleNamespace(
            id=18,
            status="lost",
            is_matched=True,
            possible_matches=json.dumps([
                {"id": 7, "source": "pending_found", "score": 0.88}
            ]),
        )
        pending = SimpleNamespace(id=7, matched_item_id=18)
        db = ScriptedDB([
            ScriptedQuery(first_value=lost),
            ScriptedQuery(first_value=None),
            ScriptedQuery(first_value=None),
        ])

        release_pending_found_link(db, pending)

        self.assertFalse(lost.is_matched)
        self.assertIsNone(lost.possible_matches)
        self.assertIsNone(pending.matched_item_id)

    def test_reanalysis_releases_proofless_ai_match_to_normal_statuses(self):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True)
        found = SimpleNamespace(id=16, status="found", is_matched=True)
        claim = SimpleNamespace(
            id=30,
            lost_item_id=18,
            found_item_id=16,
            status="pending",
            admin_decision_date=None,
        )
        db = ScriptedDB([
            ScriptedQuery(all_value=[claim]),
            ScriptedQuery(first_value=None),
            ScriptedQuery(all_value=[]),
            ScriptedQuery(all_value=[found]),
            ScriptedQuery(first_value=None),
            ScriptedQuery(first_value=None),
            ScriptedQuery(first_value=None),
        ])

        released = release_stale_ai_match_after_reanalysis(db, lost)

        self.assertEqual(released, 1)
        self.assertEqual(claim.status, "rejected")
        self.assertIsNotNone(claim.admin_decision_date)
        self.assertFalse(found.is_matched)
        self.assertFalse(lost.is_matched)
        self.assertEqual(db.flush_count, 1)

    def test_reanalysis_preserves_pending_human_claim_with_proof(self):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True)
        claim = SimpleNamespace(
            id=31,
            lost_item_id=18,
            found_item_id=16,
            status="pending",
            admin_decision_date=None,
        )
        db = ScriptedDB([
            ScriptedQuery(all_value=[claim]),
            ScriptedQuery(first_value=(44,)),
            ScriptedQuery(all_value=[]),
            ScriptedQuery(first_value=(31,)),
            ScriptedQuery(first_value=None),
        ])

        released = release_stale_ai_match_after_reanalysis(db, lost)

        self.assertEqual(released, 0)
        self.assertEqual(claim.status, "pending")
        self.assertTrue(lost.is_matched)
        self.assertEqual(db.flush_count, 0)

    @patch("item_match_lifecycle.release_stale_ai_match_after_reanalysis", return_value=1)
    def test_stronger_candidate_replaces_proofless_ai_claim(self, release_match):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True)
        old_claim = SimpleNamespace(
            id=31,
            found_item_id=16,
            similarity_score="78.0%",
        )
        db = ScriptedDB([
            ScriptedQuery(first_value=None),
            ScriptedQuery(all_value=[old_claim]),
            ScriptedQuery(all_value=[]),
            ScriptedQuery(first_value=None),
        ])

        released = replace_weaker_ai_match_after_reanalysis(
            db,
            lost,
            {"id": 22, "source": "found", "score": 0.86},
            ranked_candidates=[
                {"id": 22, "source": "found", "score": 0.86},
                {"id": 16, "source": "found", "score": 0.78},
            ],
        )

        self.assertEqual(released, 1)
        release_match.assert_called_once_with(db, lost)

    @patch("item_match_lifecycle.release_stale_ai_match_after_reanalysis")
    def test_weaker_candidate_does_not_replace_current_ai_claim(self, release_match):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True)
        old_claim = SimpleNamespace(
            id=31,
            found_item_id=16,
            similarity_score="86.0%",
        )
        db = ScriptedDB([
            ScriptedQuery(first_value=None),
            ScriptedQuery(all_value=[old_claim]),
            ScriptedQuery(all_value=[]),
            ScriptedQuery(first_value=None),
        ])

        released = replace_weaker_ai_match_after_reanalysis(
            db,
            lost,
            {"id": 22, "source": "found", "score": 0.82},
            ranked_candidates=[
                {"id": 16, "source": "found", "score": 0.86},
                {"id": 22, "source": "found", "score": 0.82},
            ],
        )

        self.assertEqual(released, 0)
        release_match.assert_not_called()

    @patch("item_match_lifecycle.release_stale_ai_match_after_reanalysis")
    def test_stronger_candidate_does_not_replace_claim_with_proof(self, release_match):
        lost = SimpleNamespace(id=18, status="lost", is_matched=True)
        old_claim = SimpleNamespace(
            id=31,
            found_item_id=16,
            similarity_score="78.0%",
        )
        db = ScriptedDB([
            ScriptedQuery(first_value=None),
            ScriptedQuery(all_value=[old_claim]),
            ScriptedQuery(all_value=[]),
            ScriptedQuery(first_value=(99,)),
        ])

        released = replace_weaker_ai_match_after_reanalysis(
            db,
            lost,
            {"id": 22, "source": "found", "score": 0.90},
            ranked_candidates=[
                {"id": 22, "source": "found", "score": 0.90},
                {"id": 16, "source": "found", "score": 0.78},
            ],
        )

        self.assertEqual(released, 0)
        release_match.assert_not_called()


if __name__ == "__main__":
    unittest.main()
