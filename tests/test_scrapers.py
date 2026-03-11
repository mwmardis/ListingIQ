"""Tests for scraper registry and ZillowScraper."""

from unittest.mock import MagicMock

import pytest

from listingiq.config import ScraperConfig, SearchConfig
from listingiq.models import ListingStatus, PropertyType
from listingiq.scrapers import SCRAPERS, get_scraper
from listingiq.scrapers.zillow import ZillowScraper


# ── Sample Zillow listing data ──

SAMPLE_LISTING = {
    "zpid": "12345678",
    "detailUrl": "/homedetails/123-Main-St/12345678_zpid/",
    "addressStreet": "123 Main St",
    "addressZipcode": "77001",
    "unformattedPrice": 350000,
    "beds": 3,
    "baths": 2.0,
    "area": 1500,
    "latLong": {
        "latitude": 29.7604,
        "longitude": -95.3698,
    },
    "hdpData": {
        "homeInfo": {
            "homeType": "SINGLE_FAMILY",
        },
    },
    "statusType": "FOR_SALE",
    "variableData": {
        "daysOnZillow": 45,
    },
}


# ── Registry Tests ──


class TestScraperRegistry:
    def test_zillow_registered(self):
        assert "zillow" in SCRAPERS
        assert SCRAPERS["zillow"] is ZillowScraper

    def test_get_scraper_zillow(self):
        cls = get_scraper("zillow")
        assert cls is ZillowScraper

    def test_get_scraper_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown scraper"):
            get_scraper("nonexistent")


# ── ZillowScraper Tests ──


class TestZillowScraper:
    def _make_scraper(self):
        cfg = ScraperConfig(search=SearchConfig(markets=["Houston, TX"]))
        return ZillowScraper(cfg)

    def test_source_name(self):
        scraper = self._make_scraper()
        assert scraper.SOURCE_NAME == "zillow"

    def test_build_search_params(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert "searchQueryState" in params
        assert "wants" in params
        assert params["requestId"] == 1

        import json

        search_state = json.loads(params["searchQueryState"])
        assert search_state["usersSearchTerm"] == "Houston, TX"
        assert search_state["filterState"]["price"]["min"] == 50000
        assert search_state["filterState"]["price"]["max"] == 500000
        assert search_state["filterState"]["beds"]["min"] == 2
        assert search_state["filterState"]["beds"]["max"] == 6
        assert search_state["filterState"]["baths"]["min"] == 1

    def test_parse_list_results_basic(self):
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([SAMPLE_LISTING], "Houston, TX")
        assert len(listings) == 1
        listing = listings[0]
        assert listing.source == "zillow"
        assert listing.source_id == "12345678"
        assert listing.address == "123 Main St"
        assert listing.city == "Houston"
        assert listing.state == "TX"
        assert listing.zip_code == "77001"
        assert listing.price == 350000.0
        assert listing.beds == 3
        assert listing.baths == 2.0
        assert listing.sqft == 1500
        assert listing.property_type == PropertyType.SINGLE_FAMILY
        assert listing.status == ListingStatus.ACTIVE
        assert listing.days_on_market == 45
        assert listing.url == "https://www.zillow.com/homedetails/123-Main-St/12345678_zpid/"

    def test_parse_list_results_raw_data(self):
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([SAMPLE_LISTING], "Houston, TX")
        assert listings[0].raw_data["zpid"] == "12345678"
        assert listings[0].raw_data["latitude"] == 29.7604
        assert listings[0].raw_data["longitude"] == -95.3698

    def test_parse_list_results_skips_no_price(self):
        bad = {**SAMPLE_LISTING, "unformattedPrice": 0, "price": 0}
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([bad], "Houston, TX")
        assert len(listings) == 0

    def test_parse_list_results_string_price(self):
        item = {**SAMPLE_LISTING, "unformattedPrice": "$275,000"}
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([item], "Houston, TX")
        assert len(listings) == 1
        assert listings[0].price == 275000.0

    def test_parse_list_results_string_sqft(self):
        item = {**SAMPLE_LISTING, "area": "1,800"}
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([item], "Houston, TX")
        assert listings[0].sqft == 1800

    def test_parse_list_results_handles_missing_fields(self):
        minimal = {
            "zpid": "99999999",
            "unformattedPrice": 200000,
        }
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([minimal], "Austin, TX")
        assert len(listings) == 1
        assert listings[0].price == 200000
        assert listings[0].beds == 0
        assert listings[0].sqft == 0
        assert listings[0].city == "Austin"
        assert listings[0].state == "TX"

    def test_parse_list_results_property_types(self):
        scraper = self._make_scraper()
        for zillow_type, expected in [
            ("SINGLE_FAMILY", PropertyType.SINGLE_FAMILY),
            ("MULTI_FAMILY", PropertyType.MULTI_FAMILY),
            ("CONDO", PropertyType.CONDO),
            ("TOWNHOUSE", PropertyType.TOWNHOUSE),
        ]:
            item = {**SAMPLE_LISTING}
            item["hdpData"] = {"homeInfo": {"homeType": zillow_type}}
            listings = scraper._parse_list_results([item], "Houston, TX")
            assert listings[0].property_type == expected

    def test_parse_list_results_statuses(self):
        scraper = self._make_scraper()
        for zillow_status, expected in [
            ("FOR_SALE", ListingStatus.ACTIVE),
            ("PENDING", ListingStatus.PENDING),
            ("SOLD", ListingStatus.SOLD),
        ]:
            item = {**SAMPLE_LISTING, "statusType": zillow_status}
            listings = scraper._parse_list_results([item], "Houston, TX")
            assert listings[0].status == expected

    def test_parse_list_results_unknown_status_defaults_active(self):
        item = {**SAMPLE_LISTING, "statusType": "UNKNOWN"}
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([item], "Houston, TX")
        assert listings[0].status == ListingStatus.ACTIVE

    def test_parse_list_results_absolute_url(self):
        item = {**SAMPLE_LISTING, "detailUrl": "https://www.zillow.com/full-url/"}
        scraper = self._make_scraper()
        listings = scraper._parse_list_results([item], "Houston, TX")
        assert listings[0].url == "https://www.zillow.com/full-url/"

    def test_parse_list_results_skips_bad_item(self):
        """Items that raise exceptions during parsing are skipped."""
        scraper = self._make_scraper()
        listings = scraper._parse_list_results(
            [SAMPLE_LISTING, "not-a-dict", SAMPLE_LISTING],
            "Houston, TX",
        )
        assert len(listings) == 2

    def test_find_list_results_nested(self):
        scraper = self._make_scraper()
        nested = {
            "some": {
                "deep": {
                    "listResults": [SAMPLE_LISTING],
                }
            }
        }
        result = scraper._find_list_results(nested)
        assert result == [SAMPLE_LISTING]

    def test_find_list_results_in_list(self):
        scraper = self._make_scraper()
        data = [{"listResults": [SAMPLE_LISTING]}]
        result = scraper._find_list_results(data)
        assert result == [SAMPLE_LISTING]

    def test_find_list_results_not_found(self):
        scraper = self._make_scraper()
        assert scraper._find_list_results({"no": "results"}) is None

    @pytest.mark.asyncio
    async def test_search_market_json_api(self):
        scraper = self._make_scraper()

        mock_response = MagicMock()
        mock_response.text = (
            '{"cat1":{"searchResults":{"listResults":'
            + f"[{__import__('json').dumps(SAMPLE_LISTING)}]"
            + "}}}"
        )

        mock_fetcher = MagicMock()
        mock_fetcher.fetch = MagicMock(return_value=mock_response)
        scraper._fetcher = mock_fetcher

        listings = await scraper.search_market("Houston, TX")

        mock_fetcher.fetch.assert_called_once()
        assert len(listings) == 1
        assert listings[0].source_id == "12345678"

    @pytest.mark.asyncio
    async def test_search_market_fallback_to_html(self):
        scraper = self._make_scraper()

        # First call (JSON API) raises, second call (HTML) returns page
        call_count = 0
        html_body = (
            '<html><script type="application/json">'
            + '{"cat1":{"searchResults":{"listResults":'
            + f"[{__import__('json').dumps(SAMPLE_LISTING)}]"
            + "}}}</script></html>"
        )

        mock_script = MagicMock()
        mock_script.css.return_value.get.return_value = (
            '{"cat1":{"searchResults":{"listResults":'
            + f"[{__import__('json').dumps(SAMPLE_LISTING)}]"
            + "}}}"
        )

        def mock_fetch(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("API blocked")
            resp = MagicMock()
            resp.text = html_body
            resp.css.return_value = [mock_script]
            return resp

        mock_fetcher = MagicMock()
        mock_fetcher.fetch = MagicMock(side_effect=mock_fetch)
        scraper._fetcher = mock_fetcher

        listings = await scraper.search_market("Houston, TX")

        assert call_count == 2
        assert len(listings) == 1

    @pytest.mark.asyncio
    async def test_search_market_all_fail_returns_empty(self):
        scraper = self._make_scraper()

        mock_fetcher = MagicMock()
        mock_fetcher.fetch = MagicMock(side_effect=Exception("blocked"))
        scraper._fetcher = mock_fetcher

        listings = await scraper.search_market("Houston, TX")
        assert listings == []

    @pytest.mark.asyncio
    async def test_close(self):
        scraper = self._make_scraper()
        scraper._fetcher = MagicMock()
        await scraper.close()
        assert scraper._fetcher is None
