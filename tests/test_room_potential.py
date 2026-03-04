"""Tests for room addition potential analysis."""
import pytest
from listingiq.analysis.room_potential import assess_room_potential
from listingiq.models import Listing


def _make_listing(**overrides) -> Listing:
    defaults = {
        "source": "test", "source_id": "test-1",
        "address": "100 Test St", "city": "Austin", "state": "TX", "zip_code": "78701",
        "price": 200_000, "beds": 3, "baths": 2, "sqft": 1400, "tax_annual": 3600,
    }
    defaults.update(overrides)
    return Listing(**defaults)


class TestRoomPotential:
    def test_no_potential_normal_ratio(self):
        listing = _make_listing(sqft=1200, beds=3)  # 400 sqft/bed
        result = assess_room_potential(listing)
        assert result["potential"] == "none"

    def test_likely_potential(self):
        listing = _make_listing(sqft=2000, beds=3)  # 667 sqft/bed
        result = assess_room_potential(listing)
        assert result["potential"] == "likely"
        assert result["sqft_per_bed"] == pytest.approx(666.7, rel=0.01)

    def test_strong_potential(self):
        listing = _make_listing(sqft=2500, beds=3)  # 833 sqft/bed
        result = assess_room_potential(listing)
        assert result["potential"] == "strong"

    def test_zero_beds_returns_none(self):
        listing = _make_listing(sqft=1500, beds=0)
        result = assess_room_potential(listing)
        assert result["potential"] == "none"

    def test_zero_sqft_returns_none(self):
        listing = _make_listing(sqft=0, beds=3)
        result = assess_room_potential(listing)
        assert result["potential"] == "none"
