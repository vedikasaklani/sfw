from fastapi.testclient import TestClient
from app.core.config import settings

# The HTTP API tests are explicitly testing the opt-in demo adapter.
settings.demo_mode = True
from app.main import app

client = TestClient(app)


def test_health_marks_sample_mode():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "demo"


def test_login_is_not_silently_enabled_in_demo_mode():
    response = client.post("/api/v1/auth/login", json={"identifier":"reader", "password":"pass"})
    assert response.status_code == 400


def test_live_mode_does_not_substitute_sample_catalogue(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "koha_client_id", "")
    monkeypatch.setattr(settings, "koha_client_secret", "")
    response = client.get("/api/v1/catalogue")
    assert response.status_code == 503
    assert "KOHA_CLIENT_ID" in response.json()["detail"]
    assert client.get("/api/v1/dashboard").status_code == 503


def test_catalogue_search_and_pagination():
    response = client.get("/api/v1/catalogue", params={"q":"nature", "page_size":1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "demo"
    assert payload["total"] >= 1
    assert len(payload["items"]) == 1


def test_book_detail_and_missing_book():
    assert client.get("/api/v1/catalogue/b-101").status_code == 200
    assert client.get("/api/v1/catalogue/missing").status_code == 404
    items = client.get("/api/v1/catalogue/b-101/items")
    assert items.status_code == 200
    assert items.json()["items"][0]["status"] == "Available"


def test_profile_interest_persistence():
    response = client.put("/api/v1/profile/interests", json={"interests":["Nature","not-a-subject"]})
    assert response.status_code == 200
    assert response.json()["interests"] == ["Nature"]


def test_profile_update_and_invalid_email():
    response = client.put("/api/v1/profile", json={"name":"Alex Reader","email":"reader@example.test"})
    assert response.status_code == 200
    assert response.json()["name"] == "Alex Reader"
    assert client.put("/api/v1/profile", json={"name":"Alex","email":"invalid"}).status_code == 422
