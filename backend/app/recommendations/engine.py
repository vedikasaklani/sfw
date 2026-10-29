"""Hybrid recommendation engine over a source-neutral RecommendationSnapshot (contract 1.0).

Pure ranking: no Koha imports, no network. Personal affinity is a feature-profile score,
blended 50/50 with the LightFM model (lightfm_model.py) when that backend is active.
"""
import math
from collections import defaultdict
from datetime import date

CONTRACT_VERSION = "1.0"
HALF_LIFE_DAYS = 120          # a read loses half its influence after ~4 months
ACTIVE_WEIGHT = 0.6           # current loans hint at taste but aren't finished reads
PREFERENCE_WEIGHT = 1.5       # explicit picks outweigh a single inferred read
FEATURE_WEIGHTS = {"author": 1.4, "series": 1.6, "subject": 1.0, "genre": 1.0, "format": 0.2, "language": 0.2}

from app.recommendations import lightfm_model

HAS_LIGHTFM = lightfm_model.AVAILABLE
BACKENDS = ("auto", "lightfm", "content")


def resolve_backend(requested: str = "auto") -> str:
    """'auto' uses LightFM when installed; 'lightfm' fails loudly instead of silently degrading."""
    if requested not in BACKENDS:
        raise ValueError(f"Unknown recommender backend {requested!r}; choose one of {', '.join(BACKENDS)}")
    if requested == "lightfm" and not HAS_LIGHTFM:
        raise RuntimeError(f"RECOMMENDER_BACKEND=lightfm but LightFM is not installed ({lightfm_model.IMPORT_ERROR}). Run: ./scripts/install_lightfm.sh")
    return "lightfm" if requested == "lightfm" or (requested == "auto" and HAS_LIGHTFM) else "content"


class ContractError(ValueError):
    pass


def validate_snapshot(snapshot: dict) -> None:
    """Checks the parts of recommendation-metadata.schema.json that scoring relies on."""
    if not isinstance(snapshot, dict) or snapshot.get("contract_version") != CONTRACT_VERSION:
        raise ContractError(f"Unsupported recommendation contract; expected {CONTRACT_VERSION}")
    for key in ("catalogue", "reader_history"):
        if not isinstance(snapshot.get(key), list):
            raise ContractError(f"Snapshot field '{key}' must be a list")
    for book in snapshot["catalogue"]:
        if not isinstance(book, dict) or not book.get("book_id") or not book.get("title"):
            raise ContractError("Every catalogue entry needs a book_id and title")
    for event in snapshot["reader_history"]:
        if not isinstance(event, dict) or not event.get("book_id") or event.get("status") not in ("active", "returned"):
            raise ContractError("Every reading event needs a book_id and an active/returned status")


def _norm(value) -> str:
    return " ".join(str(value).split()).casefold()


def book_features(book: dict) -> dict[str, tuple[str, str]]:
    """feature key -> (kind, display label). Missing metadata just yields fewer features."""
    out: dict[str, tuple[str, str]] = {}
    for kind, field in (("author", "authors"), ("author", "contributors"), ("subject", "subjects"), ("genre", "genres")):
        for value in book.get(field) or []:
            if value and str(value).strip():
                out[f"{kind}:{_norm(value)}"] = (kind, str(value).strip())
    for kind in ("series", "format", "language"):
        if book.get(kind):
            out[f"{kind}:{_norm(book[kind])}"] = (kind, str(book[kind]).strip())
    return out


def _event_weight(event: dict, today: date) -> float:
    try:
        seen = date.fromisoformat(str(event.get("returned_on") or event["checked_out_on"])[:10])
        age = max(0, (today - seen).days)
    except (KeyError, ValueError):
        age = HALF_LIFE_DAYS
    base = ACTIVE_WEIGHT if event["status"] == "active" else 1.0
    return base * 0.5 ** (age / HALF_LIFE_DAYS)


def _profile(snapshot, features_by_id, today):
    """Weighted taste profile over feature keys, plus which keys came from explicit preferences."""
    profile: dict[str, float] = defaultdict(float)
    for event in snapshot["reader_history"]:
        weight = _event_weight(event, today)
        for key, (kind, _) in features_by_id.get(event["book_id"], {}).items():
            profile[key] += weight * FEATURE_WEIGHTS[kind]
    explicit = set()
    for pref in snapshot.get("explicit_preferences") or []:
        for kind in ("subject", "genre"):
            key = f"{kind}:{_norm(pref)}"
            profile[key] += PREFERENCE_WEIGHT
            explicit.add(key)
    return profile, explicit


def _popularity(book: dict) -> float:
    pop = book.get("popularity") or {}
    return math.log1p((pop.get("checkouts") or 0) + 2 * (pop.get("holds") or 0) + 0.5 * (pop.get("renewals") or 0))


def _explain(book, features, profile, explicit, history_ids, popularity):
    contributions = sorted(((profile.get(k, 0.0), k, kind, label) for k, (kind, label) in features.items() if profile.get(k)), reverse=True)
    for _, key, kind, label in contributions:
        if kind == "series":
            return "same_series", f"Next in the {label} series"
        if kind == "author":
            return "same_author", f"More from {label}"
        if key in explicit:
            return "explicit_interest", f"Matches your interest in {label.lower()}"
        if kind in ("subject", "genre") and history_ids:
            return "similar_subject", f"Because you’ve enjoyed {label.lower()}"
    if popularity > 0:
        return "popular", "Popular at your library right now"
    return "discovery", "A fresh pick from the library’s shelves"


def recommend(snapshot: dict, limit: int = 8, today: date | None = None, backend: str = "auto", config: lightfm_model.ModelConfig = lightfm_model.DEFAULT_CONFIG) -> list[dict]:
    """Rank unread catalogue entries. Returns [{book_id, score, reason_code, reason, strategy}]."""
    validate_snapshot(snapshot)
    backend = resolve_backend(backend)
    today = today or date.today()
    features_by_id = {b["book_id"]: book_features(b) for b in snapshot["catalogue"]}
    history_ids = {e["book_id"] for e in snapshot["reader_history"]}
    profile, explicit = _profile(snapshot, features_by_id, today)
    model_scores = lightfm_model.score([b["book_id"] for b in snapshot["catalogue"]], {i: list(f) for i, f in features_by_id.items()},
                                       [(e["book_id"], _event_weight(e, today)) for e in snapshot["reader_history"]], config) if backend == "lightfm" else {}
    max_pop = max((_popularity(b) for b in snapshot["catalogue"]), default=0.0) or 1.0
    max_profile = max(profile.values(), default=0.0) or 1.0

    ranked = []
    for book in snapshot["catalogue"]:
        book_id = book["book_id"]
        if book_id in history_ids:
            continue
        features = features_by_id[book_id]
        # Content affinity: summed profile weight, damped so long subject lists don't win by volume.
        content = sum(profile.get(k, 0.0) for k in features) / (max_profile * math.sqrt(max(1, len(features))))
        personal = 0.5 * model_scores[book_id] + 0.5 * content if model_scores else content
        popularity = _popularity(book) / max_pop
        availability = {"available": 0.05, "unavailable": -0.05}.get(book.get("availability"), 0.0)
        score = round(0.8 * min(1.0, personal) + 0.15 * popularity + availability, 4)
        code, reason = _explain(book, features, profile, explicit, history_ids, _popularity(book))
        strategy = "personal" if code in ("same_series", "same_author", "explicit_interest", "similar_subject") else code
        ranked.append({"book_id": book_id, "score": score, "reason_code": code, "reason": reason, "strategy": strategy, "_title": book["title"]})
    ranked.sort(key=lambda r: (-r["score"], r["_title"].casefold()))
    return [{k: v for k, v in r.items() if k != "_title"} for r in ranked[:limit]]
