"""Tests for watchlist API endpoints and updated scan query param."""

import pytest
from fastapi.testclient import TestClient

from listingiq.config import AppConfig
from listingiq.api.server import create_app


@pytest.fixture
def client(tmp_path):
    cfg = AppConfig()
    cfg.database.url = f"sqlite:///{tmp_path / 'test.db'}"
    app = create_app(cfg)
    return TestClient(app)


class TestWatchlistAPI:
    def test_get_empty_watchlist(self, client):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_add_watchlist_entry(self, client):
        resp = client.post("/api/watchlist", json={"query": "77084"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] is not None
        assert data["query"] == "77084"

    def test_add_watchlist_entry_with_label(self, client):
        resp = client.post("/api/watchlist", json={"query": "77084", "label": "Cypress"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "Cypress"

    def test_add_duplicate_returns_409(self, client):
        client.post("/api/watchlist", json={"query": "77084"})
        resp = client.post("/api/watchlist", json={"query": "77084"})
        assert resp.status_code == 409

    def test_delete_watchlist_entry(self, client):
        resp = client.post("/api/watchlist", json={"query": "77084"})
        entry_id = resp.json()["id"]
        resp = client.delete(f"/api/watchlist/{entry_id}")
        assert resp.status_code == 200
        assert client.get("/api/watchlist").json() == []

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/watchlist/999")
        assert resp.status_code == 404

    def test_get_watchlist_returns_entries(self, client):
        client.post("/api/watchlist", json={"query": "77084"})
        client.post("/api/watchlist", json={"query": "77088"})
        resp = client.get("/api/watchlist")
        assert len(resp.json()) == 2


class TestScanQueryParam:
    def test_scan_accepts_query_param(self, client):
        """Verify the /api/scan endpoint accepts a query parameter without a 422."""
        resp = client.get("/api/scan?query=77084&source=zillow&min_score=50")
        assert resp.status_code != 422
