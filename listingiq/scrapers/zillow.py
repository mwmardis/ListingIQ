"""Zillow scraper implementation using Scrapling.

Uses Scrapling's StealthyFetcher to bypass Zillow's bot detection and
extract listing data from search results. Tries the JSON API endpoint
first, then falls back to HTML page parsing.
"""

from __future__ import annotations

import asyncio
import json
import re
from functools import partial
from urllib.parse import urlencode

from scrapling.fetchers import StealthyFetcher

from listingiq.config import ScraperConfig
from listingiq.models import Listing, ListingStatus, PropertyType
from listingiq.scrapers.base import BaseScraper

_PROPERTY_TYPE_MAP = {
    "SINGLE_FAMILY": PropertyType.SINGLE_FAMILY,
    "MULTI_FAMILY": PropertyType.MULTI_FAMILY,
    "CONDO": PropertyType.CONDO,
    "TOWNHOUSE": PropertyType.TOWNHOUSE,
}

_STATUS_MAP = {
    "FOR_SALE": ListingStatus.ACTIVE,
    "PENDING": ListingStatus.PENDING,
    "SOLD": ListingStatus.SOLD,
}

SEARCH_API_URL = "https://www.zillow.com/search/GetSearchPageState.htm"


class ZillowScraper(BaseScraper):
    """Scrape Zillow listings using Scrapling's StealthyFetcher."""

    SOURCE_NAME = "zillow"

    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        self._fetcher: StealthyFetcher | None = None

    def _get_fetcher(self) -> StealthyFetcher:
        if self._fetcher is None:
            self._fetcher = StealthyFetcher()
        return self._fetcher

    def _build_search_params(self, market: str) -> dict:
        """Build Zillow search query parameters from a market string."""
        filter_state = {
            "price": {"min": self.search.min_price, "max": self.search.max_price},
            "beds": {"min": self.search.min_beds, "max": self.search.max_beds},
            "baths": {"min": self.search.min_baths},
            "isForSaleByAgent": {"value": True},
            "isForSaleByOwner": {"value": True},
            "isNewConstruction": {"value": False},
            "isForSaleForeclosure": {"value": True},
            "isAuction": {"value": True},
        }

        return {
            "searchQueryState": json.dumps(
                {
                    "usersSearchTerm": market,
                    "filterState": filter_state,
                    "isListVisible": True,
                }
            ),
            "wants": json.dumps({"cat1": ["listResults"]}),
            "requestId": 1,
        }

    def _build_search_url(self, query: str) -> str:
        """Convert a search query (metro, zip, or neighborhood) to a Zillow URL.

        Formats:
            "Houston, TX"                    -> /houston-tx/
            "77084"                          -> /houston-tx/77084/
            "Spring Branch, Houston, TX"     -> /spring-branch-houston-tx/
        """
        query = query.strip()

        # Zip code: all digits
        if query.isdigit():
            # Use the first configured market for the metro slug
            metro = self.search.markets[0] if self.search.markets else ""
            parts = metro.split(",")
            city = parts[0].strip().replace(" ", "-").lower()
            state = parts[1].strip().lower() if len(parts) > 1 else ""
            metro_slug = f"{city}-{state}" if state else city
            return f"https://www.zillow.com/{metro_slug}/{query}/"

        # Contains commas: could be "City, ST" or "Neighborhood, City, ST"
        parts = [p.strip() for p in query.split(",")]
        slug = "-".join(parts).replace(" ", "-").lower()
        return f"https://www.zillow.com/{slug}/"

    def _filter_listings(self, listings: list[Listing]) -> list[Listing]:
        """Apply search config filters (price, beds, baths) client-side."""
        return [
            l
            for l in listings
            if self.search.min_price <= l.price <= self.search.max_price
            and self.search.min_beds <= l.beds <= self.search.max_beds
            and l.baths >= self.search.min_baths
        ]

    async def search_market(self, market: str) -> list[Listing]:
        """Search Zillow for listings in a market.

        Tries the JSON API endpoint first, falls back to HTML scraping.
        Runs the sync Playwright fetcher in a thread to avoid blocking the
        event loop.
        """
        fetcher = self._get_fetcher()

        # Primary: JSON API endpoint
        params = self._build_search_params(market)
        query_string = urlencode(params)
        api_url = f"{SEARCH_API_URL}?{query_string}"

        try:
            response = await asyncio.to_thread(fetcher.fetch, api_url)
            body = response.text
            data = json.loads(body)
            results = (
                data.get("cat1", {})
                .get("searchResults", {})
                .get("listResults", [])
            )
            if results:
                return self._filter_listings(
                    self._parse_list_results(results, market)
                )
        except (json.JSONDecodeError, AttributeError, TypeError, Exception):
            pass

        # Fallback: HTML page scraping
        return self._filter_listings(await self._scrape_html(fetcher, market))

    async def _scrape_html(self, fetcher: StealthyFetcher, market: str) -> list[Listing]:
        """Fallback: scrape the Zillow HTML search page."""
        url = self._build_search_url(market)

        try:
            response = await asyncio.to_thread(fetcher.fetch, url)
        except Exception:
            return []

        body = response.text

        # Try to extract embedded JSON from script tags
        scripts = response.css('script[type="application/json"]')
        for script in scripts:
            try:
                text = script.css("::text").get()
                if not text:
                    continue
                data = json.loads(text)
                results = self._find_list_results(data)
                if results:
                    return self._parse_list_results(results, market)
            except (json.JSONDecodeError, TypeError):
                continue

        # Regex fallback for listResults
        match = re.search(
            r'"listResults"\s*:\s*(\[.*?\])\s*[,}]',
            body,
            re.DOTALL,
        )
        if match:
            try:
                results = json.loads(match.group(1))
                return self._parse_list_results(results, market)
            except json.JSONDecodeError:
                pass

        return []

    def _find_list_results(self, data: dict | list) -> list | None:
        """Recursively search nested JSON for the listResults array."""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "listResults" and isinstance(value, list):
                    return value
                if isinstance(value, (dict, list)):
                    result = self._find_list_results(value)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = self._find_list_results(item)
                    if result:
                        return result
        return None

    def _parse_list_results(self, results: list, market: str) -> list[Listing]:
        """Parse Zillow listing result objects into Listing models."""
        listings: list[Listing] = []
        city_parts = market.split(",")
        city = city_parts[0].strip()
        state = city_parts[1].strip() if len(city_parts) > 1 else ""

        for item in results:
            try:
                price = item.get("unformattedPrice", 0) or item.get("price", 0)
                if isinstance(price, str):
                    price = float(re.sub(r"[^\d.]", "", price) or 0)
                if not price:
                    continue

                zpid = str(item.get("zpid", item.get("id", "")))
                address_info = item.get("addressStreet", item.get("address", ""))
                detail_url = item.get("detailUrl", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = f"https://www.zillow.com{detail_url}"

                beds = item.get("beds", 0) or 0
                baths = item.get("baths", 0) or 0
                sqft_raw = item.get("area", 0) or item.get("sqft", 0)
                if isinstance(sqft_raw, str):
                    sqft_raw = int(re.sub(r"[^\d]", "", sqft_raw) or 0)

                prop_type_str = (
                    item.get("hdpData", {}).get("homeInfo", {}).get("homeType", "")
                )
                prop_type = _PROPERTY_TYPE_MAP.get(
                    prop_type_str, PropertyType.SINGLE_FAMILY
                )

                status_str = item.get("statusType", "FOR_SALE")
                status = _STATUS_MAP.get(status_str, ListingStatus.ACTIVE)

                lat_long = item.get("latLong", {})

                listing = Listing(
                    source=self.SOURCE_NAME,
                    source_id=zpid,
                    url=detail_url,
                    address=address_info,
                    city=city,
                    state=state,
                    zip_code=str(item.get("addressZipcode", "")),
                    price=float(price),
                    beds=int(beds),
                    baths=float(baths),
                    sqft=int(sqft_raw),
                    property_type=prop_type,
                    status=status,
                    days_on_market=(
                        item.get("variableData", {}).get("daysOnZillow", 0)
                        or item.get("hdpData", {})
                        .get("homeInfo", {})
                        .get("daysOnZillow", 0)
                        or 0
                    ),
                    raw_data={
                        "zpid": zpid,
                        "latitude": lat_long.get("latitude"),
                        "longitude": lat_long.get("longitude"),
                    },
                )
                listings.append(listing)
            except Exception:
                continue

        return listings

    async def scrape(self) -> list[Listing]:
        return await self.scrape_all_markets()

    async def close(self) -> None:
        self._fetcher = None
