"""MLS data scrapers for various sources."""

from listingiq.scrapers.base import BaseScraper
from listingiq.scrapers.repliers import RepliersScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    "repliers": RepliersScraper,
}


def get_scraper(name: str) -> type[BaseScraper]:
    """Get a scraper class by name."""
    if name not in SCRAPERS:
        raise ValueError(f"Unknown scraper: {name}. Available: {list(SCRAPERS.keys())}")
    return SCRAPERS[name]
