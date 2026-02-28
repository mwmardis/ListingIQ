"""Zillow scraper implementation.

Uses Zillow's search results page and the embedded JSON data to extract
listings without requiring an official API key.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from listingiq.config import ScraperConfig
from listingiq.models import Listing, PropertyType, ListingStatus
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


class ZillowScraper(BaseScraper):
    SOURCE_NAME = "zillow"

    SEARCH_URL = "https://www.zillow.com/search/GetSearchPageState.htm"

    def __init__(self, config: ScraperConfig):
        super().__init__(config)

    def _build_search_params(self, market: str) -> dict:
        """Build Zillow search query parameters."""
        city_state = market.split(",")
        city = city_state[0].strip().replace(" ", "-").lower()
        state = city_state[1].strip().lower() if len(city_state) > 1 else ""
        search_term = f"{city}-{state}" if state else city

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
            "searchQueryState": json.dumps({
                "usersSearchTerm": market,
                "filterState": filter_state,
                "isListVisible": True,
            }),
            "wants": json.dumps({"cat1": ["listResults"]}),
            "requestId": 1,
        }

    async def search_market(self, market: str) -> list[Listing]:
        """Search Zillow for listings in a market."""
        client = await self._get_client()
        params = self._build_search_params(market)

        resp = await client.get(
            self.SEARCH_URL,
            params=params,
            headers={"Accept": "application/json"},
        )

        if resp.status_code != 200:
            # Fallback: try HTML parsing
            return await self._scrape_html(market)

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return await self._scrape_html(market)

        return self._parse_api_response(data, market)

    async def _scrape_html(self, market: str) -> list[Listing]:
        """Fallback: scrape the Zillow HTML search page."""
        city_state = market.split(",")
        city = city_state[0].strip().replace(" ", "-").lower()
        state = city_state[1].strip().lower() if len(city_state) > 1 else ""
        slug = f"{city}-{state}" if state else city

        client = await self._get_client()
        url = f"https://www.zillow.com/{slug}/"
        resp = await client.get(url)

        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # Zillow embeds listing data in a script tag
        script_tags = soup.find_all("script", {"type": "application/json"})
        for script in script_tags:
            try:
                data = json.loads(script.string or "")
                if "searchResults" in str(data) or "listResults" in str(data):
                    return self._parse_embedded_data(data, market)
            except (json.JSONDecodeError, TypeError):
                continue

        # Try regex as last resort
        match = re.search(
            r'"listResults"\s*:\s*(\[.*?\])\s*[,}]',
            resp.text,
            re.DOTALL,
        )
        if match:
            try:
                results = json.loads(match.group(1))
                return self._parse_list_results(results, market)
            except json.JSONDecodeError:
                pass

        return []

    def _parse_api_response(self, data: dict, market: str) -> list[Listing]:
        """Parse the JSON API response."""
        results = (
            data.get("cat1", {})
            .get("searchResults", {})
            .get("listResults", [])
        )
        return self._parse_list_results(results, market)

    def _parse_embedded_data(self, data: dict, market: str) -> list[Listing]:
        """Parse embedded JSON data from HTML."""
        # Navigate nested structure to find listing results
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "listResults" and isinstance(value, list):
                    return self._parse_list_results(value, market)
                if isinstance(value, (dict, list)):
                    result = self._parse_embedded_data(value, market)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = self._parse_embedded_data(item, market)
                    if result:
                        return result
        return []

    def _parse_list_results(self, results: list, market: str) -> list[Listing]:
        """Parse a list of Zillow result objects into Listings."""
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

                prop_type_str = item.get("hdpData", {}).get("homeInfo", {}).get("homeType", "")
                prop_type = _PROPERTY_TYPE_MAP.get(prop_type_str, PropertyType.SINGLE_FAMILY)

                status_str = item.get("statusType", "FOR_SALE")
                status = _STATUS_MAP.get(status_str, ListingStatus.ACTIVE)

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
                    days_on_market=item.get("variableData", {}).get("daysOnZillow", 0) or 0,
                    raw_data={"zpid": zpid, "latitude": item.get("latLong", {}).get("latitude"),
                              "longitude": item.get("latLong", {}).get("longitude")},
                )
                listings.append(listing)
            except Exception:
                continue

        return listings

    async def scrape(self) -> list[Listing]:
        return await self.scrape_all_markets()
