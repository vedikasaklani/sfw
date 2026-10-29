import json
from datetime import date
from pathlib import Path

import pytest

from app.integrations.koha import contract_book, extract_marc21_v1
from app.recommendations import ContractError, recommend
from app.services import demo_snapshot

DOCS = Path(__file__).resolve().parents[2] / "docs"
SNAPSHOT = json.loads((DOCS / "examples" / "recommendation-snapshot.json").read_text())
SCHEMA = json.loads((DOCS / "recommendation-metadata.schema.json").read_text())
TODAY = date(2026, 10, 29)


def book(book_id, title, **fields):
    return {"book_id": book_id, "title": title, "availability": "available", **fields}


def snapshot(catalogue, history=(), prefs=()):
    return {"contract_version": "1.0", "catalogue": list(catalogue), "reader_history": list(history), "explicit_preferences": list(prefs)}


def test_fixture_excludes_history_and_explains():
    rows = recommend(SNAPSHOT, today=TODAY)
    assert [r["book_id"] for r in rows] == ["sample-work-002"]
    assert rows[0]["reason"] and rows[0]["reason_code"]


def test_shared_author_and_subject_outrank_unrelated_books():
    cat = [book("read", "Read", authors=["Ann Lee"], subjects=["Birds"]), book("same-author", "A", authors=["Ann Lee"]),
           book("same-subject", "B", subjects=["Birds"]), book("other", "C", subjects=["Tax law"])]
    rows = recommend(snapshot(cat, [{"book_id": "read", "checked_out_on": "2026-10-01", "returned_on": "2026-10-20", "status": "returned"}]), today=TODAY)
    assert [r["book_id"] for r in rows][-1] == "other"
    assert {r["book_id"]: r["reason_code"] for r in rows}["same-author"] == "same_author"


def test_explicit_preference_drives_cold_start():
    rows = recommend(snapshot([book("a", "Alpha", subjects=["Poetry"]), book("b", "Beta", subjects=["Maps"])], prefs=["Maps"]), today=TODAY)
    assert rows[0]["book_id"] == "b" and rows[0]["reason_code"] == "explicit_interest"


def test_popularity_breaks_cold_start_without_preferences():
    rows = recommend(snapshot([book("quiet", "Quiet"), book("busy", "Busy", popularity={"checkouts": 40, "holds": 3})]), today=TODAY)
    assert [r["book_id"] for r in rows] == ["busy", "quiet"]
    assert rows[0]["reason_code"] == "popular"


def test_missing_metadata_is_not_an_error_and_ranking_is_deterministic():
    snap = snapshot([book("x", "Untagged"), book("y", "Also untagged", subjects=[], authors=None)])
    assert recommend(snap, today=TODAY) == recommend(snap, today=TODAY)


@pytest.mark.parametrize("bad", [{}, {"contract_version": "2.0", "catalogue": [], "reader_history": []},
                                 snapshot([{"book_id": "", "title": "x"}]), snapshot([], [{"book_id": "a", "status": "lost"}])])
def test_invalid_contract_is_rejected(bad):
    with pytest.raises(ContractError):
        recommend(bad)


def test_demo_snapshot_matches_schema_fields():
    snap = demo_snapshot(["Design"])
    book_keys = set(SCHEMA["$defs"]["book"]["properties"])
    event_keys = set(SCHEMA["$defs"]["readingEvent"]["properties"])
    assert all(set(b) <= book_keys for b in snap["catalogue"])
    assert all(set(e) <= event_keys for e in snap["reader_history"])


MARC = {"leader": "00000nam a2200000 a 4500", "fields": [
    {"008": "200101s2019    nyu           000 0 eng d"},
    {"100": {"ind1": "1", "ind2": " ", "subfields": [{"a": "Reed, Jonah."}]}},
    {"490": {"ind1": "0", "ind2": " ", "subfields": [{"a": "Pocket Naturalist Guides ;"}]}},
    {"520": {"ind1": " ", "ind2": " ", "subfields": [{"a": "An illustrated guide."}]}},
    {"650": {"ind1": " ", "ind2": "0", "subfields": [{"a": "Birds"}, {"z": "Ohio."}]}},
    {"651": {"ind1": " ", "ind2": "0", "subfields": [{"a": "Rivers."}]}},
    {"655": {"ind1": " ", "ind2": "7", "subfields": [{"a": "Field guides."}]}},
    {"700": {"ind1": "1", "ind2": " ", "subfields": [{"a": "Vale, R."}]}},
]}


def test_marc21_extractor_maps_known_tags():
    out = extract_marc21_v1(MARC)
    assert out["authors"] == ["Reed, Jonah"] and out["contributors"] == ["Vale, R"]
    assert out["subjects"] == ["Birds", "Rivers"] and out["genres"] == ["Field guides"]
    assert out["language"] == "eng" and out["series"] == "Pocket Naturalist Guides"
    assert extract_marc21_v1("not marc") == {}


def test_contract_book_drops_private_item_fields():
    items = [{"item_id": 9, "external_id": "BARCODE123", "internal_notes": "staff", "checked_out_date": None, "not_for_loan_status": 0, "checkouts_count": 5, "holds_count": 1}]
    entry = contract_book({"biblio_id": 42, "title": "Birds Along the River", "publication_year": "2019"}, extract_marc21_v1(MARC), items)
    assert entry["book_id"] == "42" and entry["availability"] == "available"
    assert entry["popularity"] == {"checkouts": 5, "renewals": None, "holds": 1}
    assert "BARCODE123" not in json.dumps(entry) and set(entry) <= set(SCHEMA["$defs"]["book"]["properties"])


# --- backend selection and the LightFM path ---------------------------------------------

from app.recommendations import engine as engine_module, lightfm_model, resolve_backend


def test_backend_resolution():
    assert resolve_backend("content") == "content"
    assert resolve_backend("auto") == ("lightfm" if lightfm_model.AVAILABLE else "content")
    with pytest.raises(ValueError):
        resolve_backend("tensorflow")


@pytest.mark.skipif(lightfm_model.AVAILABLE, reason="only meaningful without LightFM")
def test_forcing_lightfm_without_it_fails_loudly():
    with pytest.raises(RuntimeError, match=r"install_lightfm"):
        resolve_backend("lightfm")


def test_engine_blends_model_scores_when_lightfm_backend_is_active(monkeypatch):
    """Wiring check that runs everywhere: a stand-in model decides between two equal books."""
    seen = {}
    def fake_score(item_ids, item_features, events, config):
        seen.update(items=item_ids, events=events)
        return {i: 1.0 if i == "b" else 0.0 for i in item_ids}
    monkeypatch.setattr(lightfm_model, "score", fake_score)
    monkeypatch.setattr(engine_module, "HAS_LIGHTFM", True)
    cat = [book("read", "Read", subjects=["Maps"]), book("a", "A", subjects=["Maps"]), book("b", "B", subjects=["Maps"])]
    rows = recommend(snapshot(cat, [{"book_id": "read", "checked_out_on": "2026-10-01", "returned_on": "2026-10-10", "status": "returned"}]), today=TODAY, backend="lightfm")
    assert [r["book_id"] for r in rows] == ["b", "a"]
    assert seen["items"] == ["read", "a", "b"] and seen["events"][0][0] == "read"


lightfm_only = pytest.mark.skipif(not lightfm_model.AVAILABLE, reason="./scripts/install_lightfm.sh to run LightFM tests")


@lightfm_only
def test_lightfm_scores_are_normalised_and_deterministic():
    ids, feats = ["r", "x", "y"], {"r": ["subject:maps"], "x": ["subject:maps"], "y": ["subject:tax"]}
    first = lightfm_model.score(ids, feats, [("r", 1.0)])
    assert set(first) == set(ids) and all(0.0 <= v <= 1.0 for v in first.values())
    assert first == lightfm_model.score(ids, feats, [("r", 1.0)])
    assert first["x"] > first["y"]


@lightfm_only
def test_lightfm_backend_ranks_fixture_end_to_end():
    rows = recommend(SNAPSHOT, today=TODAY, backend="lightfm")
    assert [r["book_id"] for r in rows] == ["sample-work-002"]


@lightfm_only
def test_lightfm_ignores_history_outside_catalogue():
    assert lightfm_model.score(["a"], {"a": []}, [("missing", 1.0)]) == {}
