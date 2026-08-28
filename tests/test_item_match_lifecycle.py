import json
import unittest
from types import SimpleNamespace

from item_match_lifecycle import (
    delete_item_claims_and_release_matches,
    release_pending_found_link,
    release_stale_ai_match_after_reanalysis,
    remove_cached_possible_match,
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


if __name__ == "__main__":
    unittest.main()
