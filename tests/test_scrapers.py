"""Tests for scraper registry and RepliersScraper."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from listingiq.config import ScraperConfig, SearchConfig
from listingiq.models import PropertyType, ListingStatus
from listingiq.scrapers.repliers import RepliersScraper


# ── Sample API Response ──

SAMPLE_LISTING = {
    "mlsNumber": "H1234567",
    "resource": "Property",
    "status": "A",
    "class": "residential",
    "type": "sale",
    "listPrice": "350000",
    "listDate": "2025-01-15T00:00:00Z",
    "lastStatus": "New",
    "soldPrice": None,
    "soldDate": None,
    "originalPrice": "360000",
    "address": {
        "area": "Houston",
        "city": "Houston",
        "country": "US",
        "district": "Downtown",
        "neighborhood": "Midtown",
        "streetDirection": "",
        "streetName": "Main",
        "streetNumber": "123",
        "streetSuffix": "St",
        "unitNumber": None,
        "zip": "77001",
        "state": "Texas",
    },
    "map": {
        "latitude": "29.7604",
        "longitude": "-95.3698",
    },
    "details": {
        "numBedrooms": "3",
        "numBedroomsPlus": None,
        "numBathrooms": "2",
        "sqft": "1500",
        "propertyType": "Detached",
        "style": "2-Storey",
        "yearBuilt": "1990",
        "numGarageSpaces": "2",
        "numParkingSpaces": "4",
    },
    "lot": {
        "acres": "0.25",
        "depth": "100",
        "width": "50",
        "size": None,
    },
    "condominium": {
        "fees": {
            "maintenance": "50",
        },
    },
    "taxes": {
        "annualAmount": "4500",
    },
    "daysOnMarket": "45",
    "images": [
        "https://cdn.repliers.io/image1.jpg",
        "https://cdn.repliers.io/image2.jpg",
    ],
    "photoCount": 2,
}


# ── RepliersScraper Tests ──


class TestRepliersScraper:
    def _make_scraper(self, api_key="test-key"):
        cfg = ScraperConfig(
            api_key=api_key,
            search=SearchConfig(markets=["Houston, TX"]),
        )
        return RepliersScraper(cfg)

    def test_init_sets_api_key(self):
        scraper = self._make_scraper("my-key")
        assert scraper.api_key == "my-key"

    def test_build_params_basic(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["city"] == "Houston"
        assert params["state"] == "TX"
        assert params["status"] == "A"
        assert params["resultsPerPage"] == 500

    def test_build_params_price_range(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["minPrice"] == 50000
        assert params["maxPrice"] == 500000

    def test_build_params_bedrooms(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["minBedroomsTotal"] == 2
        assert params["maxBedroomsTotal"] == 6

    def test_build_params_bathrooms(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["minBaths"] == 1
        assert params["maxBaths"] == 4

    def test_build_params_includes_type(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert "sale" in params["type"]
        assert "lease" in params["type"]

    def test_parse_listings(self):
        scraper = self._make_scraper()
        listings = scraper._parse_listings([SAMPLE_LISTING])
        assert len(listings) == 1
        listing = listings[0]
        assert listing.source == "repliers"
        assert listing.source_id == "H1234567"
        assert listing.address == "123 Main St"
        assert listing.city == "Houston"
        assert listing.state == "Texas"
        assert listing.zip_code == "77001"
        assert listing.price == 350000.0
        assert listing.beds == 3
        assert listing.baths == 2.0
        assert listing.sqft == 1500
        assert listing.year_built == 1990
        assert listing.hoa_monthly == 50.0
        assert listing.days_on_market == 45
        assert listing.tax_annual == 4500.0
        assert listing.property_type == PropertyType.SINGLE_FAMILY
        assert listing.status == ListingStatus.ACTIVE
        assert listing.raw_data["latitude"] == "29.7604"
        assert listing.raw_data["longitude"] == "-95.3698"
        assert listing.raw_data["type"] == "sale"

    def test_parse_listings_lot_sqft_from_acres(self):
        scraper = self._make_scraper()
        listings = scraper._parse_listings([SAMPLE_LISTING])
        # 0.25 acres * 43560 sqft/acre = 10890
        assert listings[0].lot_sqft == 10890

    def test_parse_listings_skips_no_price(self):
        bad = {**SAMPLE_LISTING, "listPrice": None}
        scraper = self._make_scraper()
        listings = scraper._parse_listings([bad])
        assert len(listings) == 0

    def test_parse_listings_handles_missing_fields(self):
        minimal = {
            "mlsNumber": "H9999999",
            "listPrice": "200000",
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
        mock_response.json.return_value = {
            "page": 1,
            "numPages": 1,
            "count": 1,
            "listings": [SAMPLE_LISTING],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        scraper._client = mock_client

        listings = await scraper.search_market("Houston, TX")

        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://api.repliers.io/listings"
        assert call_args[1]["headers"]["REPLIERS-API-KEY"] == "test-key"
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

        listings = await scraper.search_market("Houston, TX")
        assert listings == []

    @pytest.mark.asyncio
    async def test_search_market_no_api_key_returns_empty(self):
        scraper = self._make_scraper(api_key="")
        listings = await scraper.search_market("Houston, TX")
        assert listings == []
