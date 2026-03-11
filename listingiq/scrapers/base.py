"""Base scraper interface."""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod

from listingiq.config import ScraperConfig
from listingiq.models import Listing


class BaseScraper(ABC):
    """Abstract base class for MLS scrapers."""

    SOURCE_NAME: str = "unknown"

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.search = config.search

    async def _delay(self) -> None:
        """Random delay between requests to be respectful."""
        delay = random.uniform(self.config.delay_min, self.config.delay_max)
        await asyncio.sleep(delay)

    @abstractmethod
    async def scrape(self) -> list[Listing]:
        """Scrape listings from this source. Must be implemented by subclasses."""
        ...

    @abstractmethod
    async def search_market(self, market: str) -> list[Listing]:
        """Search a specific market (e.g., 'Austin, TX')."""
        ...

    async def scrape_all_markets(self) -> list[Listing]:
        """Scrape all configured markets."""
        all_listings: list[Listing] = []
        for market in self.search.markets:
            listings = await self.search_market(market)
            all_listings.extend(listings)
            await self._delay()
        return all_listings

    async def close(self) -> None:
        """Clean up resources. Override in subclasses as needed."""
        pass
