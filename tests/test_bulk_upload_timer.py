import unittest
from pathlib import Path


class BulkUploadTimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "Admin Pages"
            / "User_Management.html"
        ).read_text(encoding="utf-8")

    def test_small_top_right_elapsed_timer_is_present(self):
        self.assertIn('id="bulkUploadElapsedTimer"', self.template)
        self.assertIn("position:fixed; top:18px; right:20px", self.template)
        self.assertIn("function formatBulkElapsed", self.template)

    def test_timer_tracks_the_background_job_lifecycle(self):
        self.assertIn("startBulkUploadElapsedTimer(Date.now())", self.template)
        self.assertIn("startBulkUploadElapsedTimer(job.started_at || job.created_at)", self.template)
        self.assertIn("if (job.status === 'completed') {\n        stopBulkUploadElapsedTimer();", self.template)
        self.assertIn("if (job.status === 'failed') {\n        stopBulkUploadElapsedTimer();", self.template)


if __name__ == "__main__":
    unittest.main()
