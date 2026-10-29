from collections import Counter
from datetime import date, datetime, timezone
from app.integrations.demo import BOOKS, HISTORY, LOANS
from app.recommendations import CONTRACT_VERSION, recommend


def _availability(label):
    return {"available": "available", "on loan": "unavailable", "unavailable": "unavailable"}.get(str(label).casefold(), "unknown")


def demo_snapshot(interests=None):
    """Map the sample library into the source-neutral recommendation contract."""
    return {
        "contract_version": CONTRACT_VERSION,
        "catalogue": [{"book_id": b["id"], "title": b["title"], "authors": b["authors"], "subjects": b["subjects"], "publication_year": b.get("year"), "description": b.get("description"), "availability": _availability(b["availability"])} for b in BOOKS],
        "reader_history": [{"book_id": h["book_id"], "checked_out_on": h["date"], "returned_on": h["date"], "status": "returned"} for h in HISTORY]
            + [{"book_id": l["book_id"], "checked_out_on": l["checkout_date"], "returned_on": None, "status": "active"} for l in LOANS],
        "explicit_preferences": list(interests or []),
    }


def hydrate(ranked, books):
    """Attach display records to engine output, keeping engine order."""
    by_id = {str(b["id"]): b for b in books}
    return [{**by_id[r["book_id"]], "score": r["score"], "reason": r["reason"], "reason_code": r["reason_code"], "strategy": r["strategy"]} for r in ranked if r["book_id"] in by_id]


def recommendations(limit=4, interests=None, backend="auto"):
    return hydrate(recommend(demo_snapshot(interests), limit, backend=backend), BOOKS)


def analytics():
    counts = Counter(s for b in HISTORY for s in b["subjects"])
    return {"borrowed_period": 5, "active_loans": len(LOANS), "overdue": sum(l["status"] == "Overdue" for l in LOANS), "returned": len(HISTORY), "subjects": [{"name": k, "count": v} for k, v in counts.most_common(5)], "trend": [{"month": m, "count": n} for m,n in [("Jun",2),("Jul",3),("Aug",2),("Sep",4),("Oct",3)]]}


def circulation_analytics(active_loans, returned_history, *, today=None, months=6):
    """Build patron analytics only from checkout rows supplied by Koha."""
    today = today or datetime.now(timezone.utc).date()
    month_starts = []
    year, month = today.year, today.month
    for _ in range(months):
        month_starts.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    month_starts.reverse()
    trend_counts = Counter()
    subject_counts = Counter()
    borrowed_period = 0
    returned_period = 0
    period_start = month_starts[0]
    events = [(loan, False) for loan in active_loans] + [(item, True) for item in returned_history]
    for item, returned in events:
        raw_date = item.get("checkout_date") or item.get("date")
        try:
            borrowed_on = date.fromisoformat(str(raw_date)[:10])
        except (TypeError, ValueError):
            continue
        if borrowed_on < period_start:
            continue
        borrowed_period += 1
        trend_counts[(borrowed_on.year, borrowed_on.month)] += 1
        if returned:
            returned_period += 1
        for subject in set(item.get("subjects") or []):
            clean = str(subject).strip()
            if clean:
                subject_counts[clean] += 1
    return {
        "borrowed_period": borrowed_period,
        "active_loans": len(active_loans),
        "overdue": sum(loan.get("status") == "Overdue" for loan in active_loans),
        "returned": returned_period,
        "subjects": [{"name": name, "count": count} for name, count in subject_counts.most_common(5)],
        "trend": [{"month": dt.strftime("%b"), "count": trend_counts[(dt.year, dt.month)]} for dt in month_starts],
    }
