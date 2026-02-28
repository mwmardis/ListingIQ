"""Tests for database repository."""

import os
import tempfile

import pytest

from listingiq.models import Listing, DealAnalysis, DealStrategy
from listingiq.db.repository import Repository


@pytest.fixture
def repo():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    r = Repository(f"sqlite:///{path}")
    yield r
    os.unlink(path)


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
