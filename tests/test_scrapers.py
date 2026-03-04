"""Tests for scraper field extraction."""
from listingiq.config import ScraperConfig
from listingiq.scrapers.redfin import RedfinScraper

# Minimal Redfin API response for a single home, matching the actual
# stingray API structure that _parse_listings expects.
_SAMPLE_HOME = {
    "price": {"value": 250000},
    "beds": 3,
    "baths": 2,
    "sqFt": {"value": 1500},
    "lotSize": {"value": 7000},
    "yearBuilt": {"value": 1990},
    "propertyType": 1,
    "listingStatus": "Active",
    "dom": {"value": 45},
    "hoa": {"value": 0},
    "taxInfo": {"amount": 4200},
    "mlsId": {"value": "MLS123"},
    "streetLine": {"value": "123 Main St"},
    "zip": "78701",
    "latLong": {"latitude": 30.27, "longitude": -97.74},
    "url": "/TX/Austin/123-Main-St-78701/home/12345",
    "propertyId": 12345,
    # New fields to extract
    "stories": 2,
    "pool": True,
}

_SAMPLE_RESPONSE = {"payload": {"homes": [_SAMPLE_HOME]}}


def _make_scraper() -> RedfinScraper:
    return RedfinScraper(ScraperConfig())


class TestRedfinFieldExtraction:
    def test_extracts_stories(self):
        scraper = _make_scraper()
        listings = scraper._parse_listings(_SAMPLE_RESPONSE, "Austin, TX")
        assert len(listings) == 1
        assert listings[0].stories == 2

    def test_extracts_pool(self):
        scraper = _make_scraper()
        listings = scraper._parse_listings(_SAMPLE_RESPONSE, "Austin, TX")
        assert listings[0].has_pool is True

    def test_missing_new_fields_default(self):
        """When Redfin doesn't return these fields, defaults are used."""
        home = {k: v for k, v in _SAMPLE_HOME.items() if k not in ("stories", "pool")}
        data = {"payload": {"homes": [home]}}
        scraper = _make_scraper()
        listings = scraper._parse_listings(data, "Austin, TX")
        assert listings[0].stories == 0
        assert listings[0].has_pool is None

    def test_basic_fields_still_parsed(self):
        """Ensure existing field parsing is not broken."""
        scraper = _make_scraper()
        listings = scraper._parse_listings(_SAMPLE_RESPONSE, "Austin, TX")
        listing = listings[0]
        assert listing.price == 250000
        assert listing.beds == 3
        assert listing.baths == 2
        assert listing.sqft == 1500
        assert listing.year_built == 1990
        assert listing.days_on_market == 45
        assert listing.address == "123 Main St"
        assert listing.zip_code == "78701"
