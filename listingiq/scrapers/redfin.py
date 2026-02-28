"""Redfin scraper implementation.

Redfin exposes a semi-public 'stingray' API that returns JSON data for search
results. This scraper uses that endpoint to pull listings without needing to
parse HTML.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from listingiq.config import ScraperConfig
from listingiq.models import Listing, PropertyType, ListingStatus
from listingiq.scrapers.base import BaseScraper

# Mapping from Redfin property type IDs to our enum
_PROPERTY_TYPE_MAP = {
    1: PropertyType.SINGLE_FAMILY,
    2: PropertyType.CONDO,
    3: PropertyType.TOWNHOUSE,
    4: PropertyType.MULTI_FAMILY,
    6: PropertyType.MULTI_FAMILY,
    13: PropertyType.SINGLE_FAMILY,
}

_STATUS_MAP = {
    "Active": ListingStatus.ACTIVE,
    "Pending": ListingStatus.PENDING,
    "Sold": ListingStatus.SOLD,
    "Contingent": ListingStatus.CONTINGENT,
}

# Redfin property type filter values
_RF_PROPERTY_FILTERS = {
    "single_family": 1,
    "condo": 2,
    "townhouse": 3,
    "multi_family": 4,
}


class RedfinScraper(BaseScraper):
    SOURCE_NAME = "redfin"

    BASE_URL = "https://www.redfin.com"
    STINGRAY_URL = "https://www.redfin.com/stingray/api/gis"
    SEARCH_URL = "https://www.redfin.com/stingray/do/location-autocomplete"

    def __init__(self, config: ScraperConfig):
        super().__init__(config)

    async def _resolve_market(self, market: str) -> dict | None:
        """Use Redfin's autocomplete to resolve a market name to a region."""
        client = await self._get_client()
        resp = await client.get(
            self.SEARCH_URL,
            params={"location": market, "v": 2},
        )
        if resp.status_code != 200:
            return None

        # Redfin prefixes JSON with: {}&&
        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        results = data.get("payload", {}).get("sections", [])
        for section in results:
            for row in section.get("rows", []):
                if row.get("type") == "2":  # city/region
                    return {
                        "region_id": row.get("id"),
                        "region_type": row.get("type"),
                        "url": row.get("url", ""),
                        "name": row.get("name", market),
                    }
        return None

    async def search_market(self, market: str) -> list[Listing]:
        """Search Redfin for listings in a market."""
        region = await self._resolve_market(market)
        if not region:
            return []

        await self._delay()
        client = await self._get_client()

        # Build property type filter
        uipt = ",".join(
            str(_RF_PROPERTY_FILTERS[pt])
            for pt in self.search.property_types
            if pt in _RF_PROPERTY_FILTERS
        )

        params = {
            "al": 1,
            "region_id": region["region_id"],
            "region_type": region["region_type"],
            "num_homes": 350,
            "sf": "1,2,3,5,6,7",
            "status": 1,  # active listings
            "uipt": uipt or "1,2,3,4",
            "v": 8,
        }

        if self.search.min_price:
            params["min_price"] = self.search.min_price
        if self.search.max_price:
            params["max_price"] = self.search.max_price
        if self.search.min_beds:
            params["min_num_beds"] = self.search.min_beds
        if self.search.min_baths:
            params["min_num_baths"] = self.search.min_baths

        resp = await client.get(self.STINGRAY_URL, params=params)
        if resp.status_code != 200:
            return []

        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        return self._parse_listings(data, market)

    def _parse_listings(self, data: dict, market: str) -> list[Listing]:
        """Parse Redfin API response into Listing objects."""
        listings: list[Listing] = []
        homes = data.get("payload", {}).get("homes", [])

        for home in homes:
            try:
                price = home.get("price", {}).get("value", 0)
                if not price:
                    continue

                beds = home.get("beds", 0) or 0
                baths = home.get("baths", 0) or 0
                sqft = home.get("sqFt", {}).get("value", 0) or 0
                lot_sqft = home.get("lotSize", {}).get("value", 0) or 0

                # Filter by our config
                if beds > self.search.max_beds:
                    continue
                if baths > self.search.max_baths:
                    continue

                prop_type_id = home.get("propertyType", 1)
                prop_type = _PROPERTY_TYPE_MAP.get(prop_type_id, PropertyType.SINGLE_FAMILY)

                status_text = home.get("listingStatus", "Active")
                status = _STATUS_MAP.get(status_text, ListingStatus.ACTIVE)

                # Parse location
                lat = home.get("latLong", {}).get("latitude", 0)
                lng = home.get("latLong", {}).get("longitude", 0)

                city_parts = market.split(",")
                city = city_parts[0].strip() if city_parts else ""
                state = city_parts[1].strip() if len(city_parts) > 1 else ""

                listing = Listing(
                    source=self.SOURCE_NAME,
                    source_id=str(home.get("mlsId", {}).get("value", home.get("propertyId", ""))),
                    url=self.BASE_URL + home.get("url", ""),
                    address=home.get("streetLine", {}).get("value", "Unknown"),
                    city=city,
                    state=state,
                    zip_code=str(home.get("zip", "")),
                    price=price,
                    beds=beds,
                    baths=baths,
                    sqft=sqft,
                    lot_sqft=lot_sqft,
                    year_built=home.get("yearBuilt", {}).get("value", 0) or 0,
                    property_type=prop_type,
                    status=status,
                    days_on_market=home.get("dom", {}).get("value", 0) or 0,
                    hoa_monthly=home.get("hoa", {}).get("value", 0) or 0,
                    tax_annual=home.get("taxInfo", {}).get("amount", 0) or 0,
                    raw_data={
                        "latitude": lat,
                        "longitude": lng,
                        "property_id": home.get("propertyId"),
                        "listing_id": home.get("listingId"),
                    },
                )
                listings.append(listing)
            except Exception:
                continue

        return listings

    async def scrape(self) -> list[Listing]:
        """Scrape all configured markets."""
        return await self.scrape_all_markets()
