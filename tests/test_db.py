"""Tests for database repository."""

import pytest

from listingiq.models import Listing, DealAnalysis, DealStrategy
from listingiq.db.repository import Repository


@pytest.fixture
def repo(tmp_path):
    """Create a temporary database for testing."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    return Repository(db_url)


def _make_listing(**overrides) -> Listing:
    defaults = {
        "source": "test",
        "source_id": "test-1",
        "address": "100 Test St",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78701",
        "price": 200_000,
        "beds": 3,
        "baths": 2,
        "sqft": 1400,
    }
    defaults.update(overrides)
    return Listing(**defaults)


def test_upsert_new_listing(repo):
    listing = _make_listing()
    row_id = repo.upsert_listing(listing)
    assert row_id > 0


def test_upsert_updates_existing(repo):
    listing = _make_listing(price=200_000)
    id1 = repo.upsert_listing(listing)

    listing2 = _make_listing(price=190_000)
    id2 = repo.upsert_listing(listing2)

    assert id1 == id2  # Same row updated


def test_listing_exists(repo):
    listing = _make_listing()
    repo.upsert_listing(listing)
    assert repo.listing_exists("test", "test-1")
    assert not repo.listing_exists("test", "nonexistent")


def test_save_and_get_deals(repo):
    listing = _make_listing()
    listing_id = repo.upsert_listing(listing)

    deal = DealAnalysis(
        listing=listing,
        strategy=DealStrategy.CASH_FLOW,
        score=85.0,
        metrics={"monthly_cash_flow": 350},
        meets_criteria=True,
        summary="Good deal",
    )
    deal_id = repo.save_deal(listing_id, deal)
    assert deal_id > 0

    top = repo.get_top_deals(limit=10)
    assert len(top) >= 1
    assert top[0].score == 85.0


def test_upsert_listing_with_new_fields(repo):
    """New fields (units, has_pool, etc.) are stored and retrievable."""
    listing = _make_listing(
        source_id="new-fields-1",
        units=2,
        has_pool=True,
        stories=2,
        school_rating=8.0,
        flood_zone="X",
        crime_score=2.5,
    )
    row_id = repo.upsert_listing(listing)
    row = repo.get_listing_by_id(row_id)
    assert row.units == 2
    assert row.has_pool is True
    assert row.stories == 2
    assert row.school_rating == 8.0
    assert row.flood_zone == "X"
    assert row.crime_score == 2.5


class TestWatchlist:
    def _make_repo(self, tmp_path):
        db_url = f"sqlite:///{tmp_path / 'test.db'}"
        return Repository(db_url)

    def test_add_watchlist_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        entry_id = repo.add_watchlist_entry("77084")
        assert entry_id is not None
        entries = repo.get_watchlist()
        assert len(entries) == 1
        assert entries[0].query == "77084"

    def test_add_watchlist_entry_with_label(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("77084", label="Cypress Area")
        entries = repo.get_watchlist()
        assert entries[0].label == "Cypress Area"

    def test_add_duplicate_watchlist_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("77084")
        duplicate_id = repo.add_watchlist_entry("77084")
        assert duplicate_id is None
        entries = repo.get_watchlist()
        assert len(entries) == 1

    def test_add_duplicate_case_insensitive(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("Houston, TX")
        duplicate_id = repo.add_watchlist_entry("houston, tx")
        assert duplicate_id is None

    def test_delete_watchlist_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        entry_id = repo.add_watchlist_entry("77084")
        deleted = repo.delete_watchlist_entry(entry_id)
        assert deleted is True
        assert repo.get_watchlist() == []

    def test_delete_nonexistent_entry(self, tmp_path):
        repo = self._make_repo(tmp_path)
        deleted = repo.delete_watchlist_entry(999)
        assert deleted is False

    def test_get_watchlist_ordered_by_created(self, tmp_path):
        repo = self._make_repo(tmp_path)
        repo.add_watchlist_entry("77084")
        repo.add_watchlist_entry("77088")
        repo.add_watchlist_entry("Spring Branch, Houston, TX")
        entries = repo.get_watchlist()
        assert len(entries) == 3
        assert entries[0].query == "77084"
