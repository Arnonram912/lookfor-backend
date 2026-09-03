import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from main import item_detail_owner_matches
from student_routes import edit_lost_item, edit_pending_found_item, reanalyze_student_item_edit


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class FakeSession:
    def __init__(self, *query_results):
        self.query_results = list(query_results)
        self.committed = False
        self.flushed = False

    def query(self, *args, **kwargs):
        return FakeQuery(self.query_results.pop(0))

    def commit(self):
        self.committed = True

    def flush(self):
        self.flushed = True

    def refresh(self, item):
        return None


def student_user():
    return SimpleNamespace(id=7, full_name="Test Student", first_name=None, middle_name=None, last_name=None)


def admin_user():
    return SimpleNamespace(id=99, is_admin=True, full_name="Admin User", first_name=None, middle_name=None, last_name=None)


def lost_item(*, matched=False):
    return SimpleNamespace(
        id=11,
        item_id=11,
        item_code="LOST-000011",
        status="lost",
        item_name="Old wallet",
        category_id=1,
        category="Wallet",
        brand=None,
        color=None,
        description=None,
        location="Library",
        image_path=None,
        image_embedding=None,
        date=date(2026, 8, 1),
        time_found=None,
        possible_matches='[{"id": 21, "score": 0.81}]',
        is_matched=matched,
        is_surrendered=False,
        archived=False,
        deleted=False,
        student_archived=False,
        student_deleted=False,
        user_id=7,
        report_owner_user_id=None,
        report_owner_name=None,
        report_owner_group=None,
    )


def pending_found_item(*, archived=False):
    return SimpleNamespace(
        id=12,
        item_name="Old keys",
        category="Keys",
        brand=None,
        color=None,
        description=None,
        location="Hallway",
        image_path=None,
        image_embedding=None,
        date=date(2026, 8, 1),
        time_found=None,
        matched_item_id=None,
        archived=archived,
        deleted=False,
        user_id=7,
    )


class StudentItemEditRouteTests(unittest.IsolatedAsyncioTestCase):
    @patch("main.analyze_saved_item_details")
    async def test_edit_returns_cached_matches_without_rerunning_analyzer(self, analyzer):
        item = lost_item()
        db = FakeSession()

        analysis, error = await reanalyze_student_item_edit(db, item, record_type="item")

        self.assertTrue(db.flushed)
        self.assertIsNone(error)
        self.assertEqual(analysis["highest_score"], 0.81)
        self.assertTrue(analysis["cached"])
        analyzer.assert_not_called()

    @patch("student_routes.resolve_category_name", return_value="Accessories")
    @patch("student_routes.reanalyze_student_item_edit", new_callable=AsyncMock)
    async def test_unmatched_lost_item_can_be_edited(self, reanalyze, _resolve_category):
        item = lost_item()
        db = FakeSession(item, None)
        reanalyze.return_value = ({"matched_items": [{"id": 21}], "action": "show_match"}, None)

        result = await edit_lost_item(
            item_id=item.id,
            item_name="  Blue Wallet  ",
            category=None,
            category_id=4,
            brand="  Acme ",
            color=" Blue ",
            description=" Near the desk ",
            location=" Main Library ",
            date="2026-08-02",
            time_found="09:45",
            image=None,
            extra_image_1=None,
            extra_image_2=None,
            db=db,
            current_user=student_user(),
        )

        self.assertTrue(db.committed)
        self.assertEqual(result["status"], "success")
        self.assertEqual(item.item_name, "Blue Wallet")
        self.assertEqual(item.category, "Accessories")
        self.assertEqual(item.category_id, 4)
        self.assertEqual(item.location, "Main Library")
        self.assertEqual(item.time_found, "09:45")
        self.assertEqual(result["analysis"]["action"], "show_match")
        reanalyze.assert_awaited_once_with(db, item, record_type="item")

    async def test_matched_lost_item_is_rejected(self):
        item = lost_item(matched=True)
        db = FakeSession(item)

        with self.assertRaises(HTTPException) as error:
            await edit_lost_item(
                item_id=item.id,
                item_name="Wallet",
                category="Wallet",
                category_id=1,
                brand=None,
                color=None,
                description=None,
                location="Library",
                date="2026-08-02",
                time_found=None,
                image=None,
                extra_image_1=None,
                extra_image_2=None,
                db=db,
                current_user=student_user(),
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(db.committed)

    @patch("student_routes.resolve_category_name", return_value="Electronics")
    @patch("student_routes.reanalyze_student_item_edit", new_callable=AsyncMock)
    async def test_pending_found_item_can_be_edited(self, reanalyze, _resolve_category):
        item = pending_found_item()
        db = FakeSession(item)
        reanalyze.return_value = ({"matched_items": [], "action": "no_match"}, None)

        result = await edit_pending_found_item(
            item_id=item.id,
            item_name="Earbuds",
            category=None,
            category_id=5,
            brand="Sound Co",
            color="Black",
            description="In a case",
            location="Room 201",
            date="2026-08-02",
            time_found="14:20",
            image=None,
            extra_image_1=None,
            extra_image_2=None,
            db=db,
            current_user=student_user(),
        )

        self.assertTrue(db.committed)
        self.assertEqual(result["status"], "success")
        self.assertEqual(item.category, "Electronics")
        self.assertEqual(item.item_name, "Earbuds")
        self.assertEqual(item.time_found, "14:20")
        self.assertEqual(result["analysis"]["action"], "no_match")
        reanalyze.assert_awaited_once_with(db, item, record_type="pending-found")

    async def test_archived_pending_found_item_is_rejected(self):
        item = pending_found_item(archived=True)
        db = FakeSession(item)

        with self.assertRaises(HTTPException) as error:
            await edit_pending_found_item(
                item_id=item.id,
                item_name="Keys",
                category="Keys",
                category_id=1,
                brand=None,
                color=None,
                description=None,
                location="Hallway",
                date="2026-08-02",
                time_found=None,
                image=None,
                extra_image_1=None,
                extra_image_2=None,
                db=db,
                current_user=student_user(),
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse(db.committed)

    def test_admin_cannot_edit_someone_elses_item_details(self):
        item = lost_item()

        self.assertFalse(item_detail_owner_matches(item, admin_user()))


if __name__ == "__main__":
    unittest.main()
