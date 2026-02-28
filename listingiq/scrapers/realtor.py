"""Realtor.com scraper implementation.

Uses Realtor.com's internal GraphQL API to fetch listing data.
"""

from __future__ import annotations

import json
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from listingiq.config import ScraperConfig
from listingiq.models import Listing, PropertyType, ListingStatus
from listingiq.scrapers.base import BaseScraper

_PROPERTY_TYPE_MAP = {
    "single_family": PropertyType.SINGLE_FAMILY,
    "multi_family": PropertyType.MULTI_FAMILY,
    "condos": PropertyType.CONDO,
    "condo": PropertyType.CONDO,
    "townhomes": PropertyType.TOWNHOUSE,
    "townhouse": PropertyType.TOWNHOUSE,
}

_STATUS_MAP = {
    "for_sale": ListingStatus.ACTIVE,
    "pending": ListingStatus.PENDING,
    "sold": ListingStatus.SOLD,
    "contingent": ListingStatus.CONTINGENT,
}


class RealtorScraper(BaseScraper):
    SOURCE_NAME = "realtor"

    API_URL = "https://www.realtor.com/api/v1/hulk"
    SEARCH_BASE = "https://www.realtor.com/realestateandhomes-search"

    def __init__(self, config: ScraperConfig):
        super().__init__(config)

    def _build_query(self, market: str) -> dict:
        """Build the GraphQL-like query for Realtor.com's API."""
        city_state = market.split(",")
        city = city_state[0].strip()
        state = city_state[1].strip() if len(city_state) > 1 else ""

        prop_types = []
        for pt in self.search.property_types:
            if pt in _PROPERTY_TYPE_MAP:
                prop_types.append(pt)

        return {
            "query": {
                "status": ["for_sale"],
                "primary": True,
                "search_location": {"location": f"{city}, {state}"},
            },
            "limit": 200,
            "offset": 0,
            "sort": {"field": "list_date", "direction": "desc"},
        }

    async def search_market(self, market: str) -> list[Listing]:
        """Search Realtor.com for listings."""
        # Try scraping the HTML search page
        city_state = market.split(",")
        city = city_state[0].strip().replace(" ", "_")
        state = city_state[1].strip() if len(city_state) > 1 else ""

        slug = f"{city}_{state}"
        search_url = f"{self.SEARCH_BASE}/{slug}"

        params = {}
        if self.search.min_price:
            params["price_min"] = self.search.min_price
        if self.search.max_price:
            params["price_max"] = self.search.max_price
        if self.search.min_beds:
            params["beds_min"] = self.search.min_beds
        if self.search.min_baths:
            params["baths_min"] = self.search.min_baths

        client = await self._get_client()
        resp = await client.get(search_url, params=params)

        if resp.status_code != 200:
            return []

        return self._parse_html(resp.text, market)

    def _parse_html(self, html: str, market: str) -> list[Listing]:
        """Parse Realtor.com HTML for listing data."""
        listings: list[Listing] = []
        soup = BeautifulSoup(html, "lxml")

        city_parts = market.split(",")
        city = city_parts[0].strip()
        state = city_parts[1].strip() if len(city_parts) > 1 else ""

        # Realtor.com embeds listing data in __NEXT_DATA__
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                next_data = json.loads(script.string)
                properties = (
                    next_data.get("props", {})
                    .get("pageProps", {})
                    .get("properties", [])
                )
                if not properties:
                    # Try alternative path
                    properties = (
                        next_data.get("props", {})
                        .get("pageProps", {})
                        .get("searchResults", {})
                        .get("home_search", {})
                        .get("results", [])
                    )
                return self._parse_properties(properties, city, state)
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback: parse card elements
        cards = soup.select("[data-testid='property-card'], .property-card, .srp-item")
        for card in cards:
            try:
                listing = self._parse_card(card, city, state)
                if listing:
                    listings.append(listing)
            except Exception:
                continue

        return listings

    def _parse_properties(self, properties: list, city: str, state: str) -> list[Listing]:
        """Parse property objects from Realtor.com's embedded data."""
        listings: list[Listing] = []

        for prop in properties:
            try:
                location = prop.get("location", {})
                address_info = location.get("address", {})
                description = prop.get("description", {})

                price = prop.get("list_price", 0) or description.get("list_price", 0)
                if not price:
                    continue

                beds = description.get("beds", 0) or 0
                baths = description.get("baths", 0) or 0
                sqft = description.get("sqft", 0) or 0
                lot_sqft = description.get("lot_sqft", 0) or 0

                prop_type_str = description.get("type", "single_family")
                prop_type = _PROPERTY_TYPE_MAP.get(prop_type_str, PropertyType.SINGLE_FAMILY)

                status_str = prop.get("status", "for_sale")
                status = _STATUS_MAP.get(status_str, ListingStatus.ACTIVE)

                property_id = str(prop.get("property_id", ""))
                permalink = prop.get("permalink", "")
                url = f"https://www.realtor.com/realestateandhomes-detail/{permalink}" if permalink else ""

                listing = Listing(
                    source=self.SOURCE_NAME,
                    source_id=property_id,
                    url=url,
                    address=address_info.get("line", ""),
                    city=address_info.get("city", city),
                    state=address_info.get("state_code", state),
                    zip_code=str(address_info.get("postal_code", "")),
                    price=float(price),
                    beds=int(beds),
                    baths=float(baths),
                    sqft=int(sqft),
                    lot_sqft=int(lot_sqft),
                    year_built=description.get("year_built", 0) or 0,
                    property_type=prop_type,
                    status=status,
                    days_on_market=prop.get("list_date_diff", 0) or 0,
                    tax_annual=prop.get("tax_record", {}).get("public_record_amount", 0) or 0,
                    raw_data={
                        "property_id": property_id,
                        "latitude": location.get("coordinate", {}).get("lat"),
                        "longitude": location.get("coordinate", {}).get("lon"),
                    },
                )
                listings.append(listing)
            except Exception:
                continue

        return listings

    def _parse_card(self, card, city: str, state: str) -> Listing | None:
        """Parse a single property card HTML element."""
        price_el = card.select_one("[data-testid='card-price'], .card-price, .price")
        if not price_el:
            return None

        price_text = price_el.get_text(strip=True)
        import re
        price = float(re.sub(r"[^\d.]", "", price_text) or 0)
        if not price:
            return None

        address_el = card.select_one("[data-testid='card-address'], .card-address")
        address = address_el.get_text(strip=True) if address_el else "Unknown"

        # Extract beds/baths/sqft from meta line
        meta_els = card.select("[data-testid='property-meta'] li, .property-meta li")
        beds, baths, sqft = 0, 0, 0
        for meta in meta_els:
            text = meta.get_text(strip=True).lower()
            import re as _re
            nums = _re.findall(r"[\d.]+", text)
            if nums:
                if "bed" in text:
                    beds = int(float(nums[0]))
                elif "bath" in text:
                    baths = float(nums[0])
                elif "sqft" in text or "sq ft" in text:
                    sqft = int(float(nums[0].replace(",", "")))

        link = card.select_one("a[href]")
        url = ""
        if link:
            href = link.get("href", "")
            url = href if href.startswith("http") else f"https://www.realtor.com{href}"

        return Listing(
            source=self.SOURCE_NAME,
            source_id=url.split("/")[-1] if url else str(hash(address)),
            url=url,
            address=address,
            city=city,
            state=state,
            zip_code="",
            price=price,
            beds=beds,
            baths=baths,
            sqft=sqft,
        )

    async def scrape(self) -> list[Listing]:
        return await self.scrape_all_markets()
