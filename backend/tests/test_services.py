from app.services import recommendations, analytics


def test_recommendations_exclude_already_read_books_and_explain():
    rows = recommendations(8)
    ids = {row["id"] for row in rows}
    assert "b-101" not in ids
    assert "b-104" not in ids
    assert all(row["reason"] for row in rows)


def test_analytics_report_consistent_demo_counts():
    result = analytics()
    assert result["active_loans"] == 2
    assert result["overdue"] == 1
    assert result["returned"] == 3
    assert result["trend"]
