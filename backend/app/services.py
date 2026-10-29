from collections import Counter
from datetime import date
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
