import asyncio
import unittest
from types import SimpleNamespace

from admin_routes import get_stats


class CountQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return self.value


class CountSession:
    def __init__(self, counts):
        self.counts = iter(counts)

    def query(self, *args, **kwargs):
        return CountQuery(next(self.counts))


class DashboardStatsTests(unittest.TestCase):
    def test_dashboard_returns_database_counts_for_lost_and_found(self):
        db = CountSession([4, 3, 17, 21])

        result = asyncio.run(get_stats(
            db=db,
            current_admin=SimpleNamespace(email="admin@example.com"),
        ))

        self.assertEqual(result["claimed_count"], 4)
        self.assertEqual(result["pending_count"], 3)
        self.assertEqual(result["lost_count"], 17)
        self.assertEqual(result["found_count"], 21)


if __name__ == "__main__":
    unittest.main()
