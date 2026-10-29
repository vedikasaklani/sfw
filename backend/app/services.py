from collections import Counter
from datetime import date, datetime, timezone
from app.integrations.demo import BOOKS, HISTORY, LOANS


def recommendations(limit=4):
    interests = Counter(subject for item in HISTORY for subject in item["subjects"])
    already = {item["book_id"] for item in HISTORY} | {item["book_id"] for item in LOANS}
    ranked = []
    for book in BOOKS:
        if book["id"] in already: continue
        overlap = [(s, interests[s]) for s in book["subjects"] if interests[s]]
        score = sum(n for _, n in overlap) * 10 + (5 if book["availability"] == "Available" else 0)
        reason = f"Because you’ve enjoyed {overlap[0][0].lower()}" if overlap else "A fresh pick from the library’s shelves"
        ranked.append({**book, "score": score, "reason": reason, "strategy": "personal" if overlap else "new-arrival"})
    return sorted(ranked, key=lambda b: (b["score"], b["added"]), reverse=True)[:limit]


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
