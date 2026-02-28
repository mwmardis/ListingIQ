"""MLS data scrapers for various sources."""

from listingiq.scrapers.base import BaseScraper
from listingiq.scrapers.redfin import RedfinScraper
from listingiq.scrapers.zillow import ZillowScraper
from listingiq.scrapers.realtor import RealtorScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    "redfin": RedfinScraper,
    "zillow": ZillowScraper,
    "realtor": RealtorScraper,
}


def get_scraper(name: str) -> type[BaseScraper]:
    """Get a scraper class by name."""
    if name not in SCRAPERS:
        raise ValueError(f"Unknown scraper: {name}. Available: {list(SCRAPERS.keys())}")
    return SCRAPERS[name]
