"""Tests for data models."""

from listingiq.models import Listing, PropertyType, ListingStatus


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
