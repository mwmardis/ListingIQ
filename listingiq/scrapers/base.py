"""Base scraper interface."""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod

import httpx

from listingiq.config import ScraperConfig, SearchConfig
from listingiq.models import Listing


class BaseScraper(ABC):
    """Abstract base class for MLS scrapers."""

    SOURCE_NAME: str = "unknown"

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.search = config.search
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

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
        if self._client and not self._client.is_closed:
            await self._client.aclose()
