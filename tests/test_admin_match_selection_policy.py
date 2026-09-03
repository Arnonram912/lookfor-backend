import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class AdminMatchSelectionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        cls.manual_claim = source.split(
            '@app.post("/api/admin/manual-claim")', 1
        )[1].split('@app.post(', 1)[0]

    def test_reselecting_current_pair_keeps_existing_claim(self):
        self.assertIn("existing_pair_claim =", self.manual_claim)
        existing_check = self.manual_claim.index("if existing_pair_claim:")
        release = self.manual_claim.index("release_stale_ai_match_after_reanalysis")
        self.assertLess(existing_check, release)
        self.assertIn('"existing": True', self.manual_claim)

    def test_switch_unlinks_previous_pending_pair_before_linking_new_pair(self):
        release = self.manual_claim.index("release_stale_ai_match_after_reanalysis")
        create = self.manual_claim.index("new_claim = models.Claim(")
        self.assertLess(release, create)
        self.assertIn("Previous pending match unlinked", self.manual_claim)

    def test_selected_pair_is_marked_and_sent_to_claim_management(self):
        self.assertIn("lost_item.is_matched = True", self.manual_claim)
        self.assertIn("found_item.is_matched = True", self.manual_claim)
        self.assertIn('status="pending"', self.manual_claim)
        self.assertIn('"target_url": "/admin/Claim-Management"', self.manual_claim)


if __name__ == "__main__":
    unittest.main()
