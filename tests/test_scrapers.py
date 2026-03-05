"""Tests for scraper registry."""
from listingiq.scrapers import SCRAPERS, get_scraper
from listingiq.scrapers.zillow import ZillowScraper


class TestScraperRegistry:
    def test_zillow_is_registered(self):
        assert "zillow" in SCRAPERS
        assert SCRAPERS["zillow"] is ZillowScraper

    def test_get_scraper_returns_zillow(self):
        assert get_scraper("zillow") is ZillowScraper

    def test_get_scraper_unknown_raises(self):
        try:
            get_scraper("redfin")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
