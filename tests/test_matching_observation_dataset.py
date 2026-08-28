import csv
import tempfile
import unittest
from pathlib import Path

from matching_observation_dataset import record_match_observations


class MatchingObservationDatasetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.observations = root / "observations.csv"

    @staticmethod
    def _rows(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))

    def test_observation_upsert_does_not_create_duplicate_pairs(self):
        candidate = {
            "lost_item_id": 10,
            "found_item_id": 20,
            "candidate_source": "found",
            "image_similarity": 0.91,
            "text_similarity": 0.82,
            "detail_similarity": 0.75,
            "raw_score": 0.86,
            "score": 0.83,
            "predicted_match": True,
        }
        record_match_observations(
            lost_item_id=10,
            found_item_id=20,
            candidate_source="found",
            candidates=[candidate],
            path=self.observations,
        )
        candidate["score"] = 0.81
        record_match_observations(
            lost_item_id=10,
            found_item_id=20,
            candidate_source="found",
            candidates=[candidate],
            path=self.observations,
        )

        rows = self._rows(self.observations)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pair_key"], "10:found:20")
        self.assertEqual(rows[0]["final_confidence"], "0.8100")
        self.assertEqual(rows[0]["predicted_match"], "true")

if __name__ == "__main__":
    unittest.main()
