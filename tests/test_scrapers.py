"""Tests for scraper registry and RentcastScraper."""
import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from listingiq.config import ScraperConfig, SearchConfig
from listingiq.models import Listing, PropertyType, ListingStatus
from listingiq.scrapers.rentcast import RentcastScraper


# ── Sample API Response ──

SAMPLE_LISTING = {
    "id": "rc-123",
    "formattedAddress": "123 Main St, Austin, TX 78701",
    "addressLine1": "123 Main St",
    "city": "Austin",
    "state": "TX",
    "zipCode": "78701",
    "latitude": 30.267,
    "longitude": -97.743,
    "propertyType": "Single Family",
    "bedrooms": 3,
    "bathrooms": 2,
    "squareFootage": 1500,
    "lotSize": 5000,
    "yearBuilt": 1990,
    "hoa": 50.0,
    "status": "Active",
    "price": 350000,
    "listedDate": "2025-01-15",
    "daysOnMarket": 45,
}


# ── RentcastScraper Tests ──

class TestRentcastScraper:
    def _make_scraper(self, api_key="test-key"):
        cfg = ScraperConfig(
            api_key=api_key,
            search=SearchConfig(markets=["Austin, TX"]),
        )
        return RentcastScraper(cfg)

    def test_init_sets_api_key(self):
        scraper = self._make_scraper("my-key")
        assert scraper.api_key == "my-key"

    def test_build_params_basic(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Austin, TX")
        assert params["city"] == "Austin"
        assert params["state"] == "TX"
        assert "price" in params

    def test_build_params_price_range(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Austin, TX")
        assert params["price"] == "50000:500000"

    def test_build_params_bedrooms_range(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Austin, TX")
        assert params["bedrooms"] == "2:6"

    def test_parse_listings(self):
        scraper = self._make_scraper()
        listings = scraper._parse_listings([SAMPLE_LISTING])
        assert len(listings) == 1
        listing = listings[0]
        assert listing.source == "rentcast"
        assert listing.source_id == "rc-123"
        assert listing.address == "123 Main St, Austin, TX 78701"
        assert listing.city == "Austin"
        assert listing.state == "TX"
        assert listing.zip_code == "78701"
        assert listing.price == 350000
        assert listing.beds == 3
        assert listing.baths == 2
        assert listing.sqft == 1500
        assert listing.lot_sqft == 5000
        assert listing.year_built == 1990
        assert listing.hoa_monthly == 50.0
        assert listing.days_on_market == 45
        assert listing.property_type == PropertyType.SINGLE_FAMILY
        assert listing.status == ListingStatus.ACTIVE

    def test_parse_listings_skips_no_price(self):
        bad = {**SAMPLE_LISTING, "price": None}
        scraper = self._make_scraper()
        listings = scraper._parse_listings([bad])
        assert len(listings) == 0

    def test_parse_listings_handles_missing_fields(self):
        minimal = {
            "id": "rc-456",
            "price": 200000,
        }
        scraper = self._make_scraper()
        listings = scraper._parse_listings([minimal])
        assert len(listings) == 1
        assert listings[0].price == 200000
        assert listings[0].beds == 0
        assert listings[0].sqft == 0

    @pytest.mark.asyncio
    async def test_search_market_calls_api(self):
        scraper = self._make_scraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [SAMPLE_LISTING]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        scraper._client = mock_client

        listings = await scraper.search_market("Austin, TX")

        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://api.rentcast.io/v1/listings/sale"
        assert call_args[1]["headers"]["X-Api-Key"] == "test-key"
        assert len(listings) == 1

    @pytest.mark.asyncio
    async def test_search_market_returns_empty_on_error(self):
        scraper = self._make_scraper()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        scraper._client = mock_client

        listings = await scraper.search_market("Austin, TX")
        assert listings == []

    @pytest.mark.asyncio
    async def test_search_market_no_api_key_returns_empty(self):
        scraper = self._make_scraper(api_key="")
        listings = await scraper.search_market("Austin, TX")
        assert listings == []
