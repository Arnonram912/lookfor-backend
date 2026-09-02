from types import SimpleNamespace
from unittest.mock import patch

from main import analyze_found_upload_from_lost_side


class FakeQuery:
    def __init__(self, items):
        self.items = items

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.items


class FakeSession:
    def __init__(self, lost_items):
        self.lost_items = lost_items

    def query(self, *args, **kwargs):
        return FakeQuery(self.lost_items)


def lost_item(item_id):
    return SimpleNamespace(
        id=item_id,
        item_name=f"Lost item {item_id}",
        category="Wallet",
        location="Library",
        image_path=f"lost-{item_id}.jpg",
        brand=None,
        color="Black",
        description="Black wallet",
    )


def uploaded_candidate(item_id, score, rank):
    return {
        "id": item_id,
        "source": "pending_found",
        "score": score,
        "raw_score": score,
        "rank": rank,
        "available_for_match": True,
    }


@patch("main.analyze_saved_item_details")
def test_found_upload_is_selected_by_the_lost_reports_analysis(analyzer):
    first_lost = lost_item(11)
    second_lost = lost_item(22)
    uploaded = SimpleNamespace(id=99)
    analyzer.side_effect = [
        {
            "ranked_candidates": [
                {"id": 55, "source": "found", "score": 0.86},
                uploaded_candidate(99, 0.80, 2),
            ],
            "matched_items": [uploaded_candidate(99, 0.80, 2)],
        },
        {
            "ranked_candidates": [uploaded_candidate(99, 0.82, 1)],
            "matched_items": [uploaded_candidate(99, 0.82, 1)],
        },
    ]

    result = analyze_found_upload_from_lost_side(
        FakeSession([first_lost, second_lost]),
        uploaded,
        record_type="pending-found",
    )

    assert result["matched_item"]["id"] == second_lost.id
    assert result["matched_item"]["source"] == "lost"
    assert [entry["lost_item"].id for entry in result["automatic_matches"]] == [
        second_lost.id
    ]
    assert analyzer.call_count == 2


def test_found_upload_lost_side_analysis_rejects_non_found_record_type():
    try:
        analyze_found_upload_from_lost_side(
            FakeSession([]),
            SimpleNamespace(id=99),
            record_type="item",
        )
    except ValueError as exc:
        assert "found record type" in str(exc)
    else:
        raise AssertionError("Expected a ValueError for a lost record type")
