from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from admin_routes import get_claimed_items


class FakeClaimQuery:
    def __init__(self, claims):
        self.claims = claims

    def options(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.claims


class FakeSession:
    def __init__(self, claims):
        self.claims = claims

    def query(self, *args, **kwargs):
        return FakeClaimQuery(self.claims)


@patch(
    "admin_routes.serialize_inventory_item",
    side_effect=lambda _db, item: {"id": item.id, "item_name": item.item_name},
)
def test_claimed_inventory_returns_the_lost_found_pair_with_claimant_details(_serialize):
    decided_at = datetime(2026, 9, 2, 10, 30)
    claim = SimpleNamespace(
        id=41,
        status="claimed",
        similarity_score="88.0%",
        admin_decision_date=decided_at,
        created_at=datetime(2026, 9, 1, 9, 0),
        lost_item=SimpleNamespace(id=11, item_name="Lost wallet"),
        found_item=SimpleNamespace(id=22, item_name="Found wallet"),
        claimant=SimpleNamespace(
            id=7,
            full_name="Alex Student",
            first_name=None,
            middle_name=None,
            last_name=None,
            student_no="2026-0001",
            course="BSIT",
            department=None,
        ),
    )

    result = get_claimed_items(
        db=FakeSession([claim]),
        current_admin=SimpleNamespace(id=1),
    )

    assert result == [{
        "claim_id": 41,
        "status": "Claimed Item",
        "similarity": "88.0%",
        "claimed_at": decided_at.isoformat(),
        "claimant": {
            "id": 7,
            "name": "Alex Student",
            "student_no": "2026-0001",
            "course": "BSIT",
            "department": None,
        },
        "lost_item": {"id": 11, "item_name": "Lost wallet"},
        "found_item": {"id": 22, "item_name": "Found wallet"},
    }]


def test_claimed_items_page_uses_its_own_menu_destination_and_api():
    project_root = Path(__file__).resolve().parents[1]
    template = (project_root / "templates" / "Admin Pages" / "Claimed_Items.html").read_text(
        encoding="utf-8"
    )

    assert 'href="/admin/Claimed-Items"' in template
    assert "fetch('/admin/items/claimed'" in template
    assert "Lost Item Details" in template
    assert "Found Item Details" in template
    assert 'class="claimed-detail-image"' in template
    assert "width:min(1400px" in template
    sidebar = template.split("</nav>", 1)[0]
    assert sidebar.index("/admin/Found_Items_Report") < sidebar.index("/admin/Claimed-Items")
    assert sidebar.index("/admin/Claimed-Items") < sidebar.index("/admin/Claim-Management")


def test_settings_sidebar_contains_every_admin_menu_link():
    project_root = Path(__file__).resolve().parents[1]
    template = (project_root / "templates" / "Admin Pages" / "Setting.html").read_text(
        encoding="utf-8"
    )
    sidebar = template.split("</nav>", 1)[0]

    expected_destinations = (
        "/admin/dashboard",
        "/admin/Messages",
        "/admin/User-Management",
        "/admin/Lost_Items_Report",
        "/admin/Found_Items_Report",
        "/admin/Claimed-Items",
        "/admin/Claim-Management",
        "/admin/Confiscated-items",
        "/admin/Reports",
        "/admin/Profile",
        "/admin/Settings",
        "/admin/Content-management",
    )
    for destination in expected_destinations:
        assert destination in sidebar
    assert "/static/admin2.o.css?v=18" in template
    assert "/static/session-keepalive.js?v=18" in template

    sidebar_script = (project_root / "static" / "session-keepalive.js").read_text(
        encoding="utf-8"
    )
    assert 'currentAdminPath === "/admin/settings"' not in sidebar_script
    assert '"For Disposal"' in sidebar_script
    assert '"Audit Logs"' in sidebar_script
