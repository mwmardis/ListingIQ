"""Tests for data models."""

from listingiq.models import Listing, PropertyType, ListingStatus, UnitMix


def test_listing_creation():
    listing = Listing(
        source="test",
        source_id="123",
        address="123 Main St",
        city="Austin",
        state="TX",
        zip_code="78701",
        price=250_000,
        beds=3,
        baths=2,
        sqft=1500,
    )
    assert listing.price == 250_000
    assert listing.full_address == "123 Main St, Austin, TX 78701"


def test_listing_price_per_sqft():
    listing = Listing(
        source="test",
        source_id="123",
        address="123 Main St",
        city="Austin",
        state="TX",
        zip_code="78701",
        price=300_000,
        sqft=1500,
    )
    assert listing.price_per_sqft == 200.0


def test_listing_price_per_sqft_zero_sqft():
    listing = Listing(
        source="test",
        source_id="123",
        address="123 Main St",
        city="Austin",
        state="TX",
        zip_code="78701",
        price=300_000,
        sqft=0,
    )
    assert listing.price_per_sqft == 0.0


def test_listing_defaults():
    listing = Listing(
        source="test",
        source_id="456",
        address="456 Oak Ave",
        city="Dallas",
        state="TX",
        zip_code="75201",
        price=150_000,
    )
    assert listing.beds == 0
    assert listing.baths == 0
    assert listing.property_type == PropertyType.SINGLE_FAMILY
    assert listing.status == ListingStatus.ACTIVE
    assert listing.hoa_monthly == 0.0


# --- Helper for new-field tests ---

def _make_listing(**overrides) -> Listing:
    defaults = {
        "source": "test",
        "source_id": "test-1",
        "address": "100 Investor Blvd",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78701",
        "price": 200_000,
        "beds": 3,
        "baths": 2,
        "sqft": 1400,
        "tax_annual": 3600,
    }
    defaults.update(overrides)
    return Listing(**defaults)


class TestListingNewFields:
    def test_defaults_backward_compatible(self):
        """Existing listing creation still works without new fields."""
        listing = _make_listing()
        assert listing.units == 1
        assert listing.has_pool is None
        assert listing.stories == 0
        assert listing.school_rating is None
        assert listing.flood_zone is None
        assert listing.crime_score is None

    def test_new_fields_set_explicitly(self):
        listing = _make_listing(
            units=2, has_pool=True, stories=2,
            school_rating=7.5, flood_zone="X", crime_score=3.2,
        )
        assert listing.units == 2
        assert listing.has_pool is True
        assert listing.stories == 2
        assert listing.school_rating == 7.5
        assert listing.flood_zone == "X"
        assert listing.crime_score == 3.2

    def test_multi_family_units(self):
        listing = _make_listing(units=4)
        assert listing.units == 4


class TestUnitMix:
    def test_create_unit_mix(self):
        unit = UnitMix(unit_number=1, beds=2, baths=1, sqft=800, estimated_rent=1200.0)
        assert unit.unit_number == 1
        assert unit.estimated_rent == 1200.0
