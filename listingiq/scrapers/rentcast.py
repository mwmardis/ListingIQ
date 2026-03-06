"""Rentcast API scraper implementation.

Uses the Rentcast Sale Listings API to fetch active property listings
for investment analysis.
"""

from __future__ import annotations

from listingiq.config import ScraperConfig
from listingiq.models import Listing, PropertyType, ListingStatus
from listingiq.scrapers.base import BaseScraper

_PROPERTY_TYPE_MAP = {
    "Single Family": PropertyType.SINGLE_FAMILY,
    "Multi-Family": PropertyType.MULTI_FAMILY,
    "Condo": PropertyType.CONDO,
    "Townhouse": PropertyType.TOWNHOUSE,
}

_STATUS_MAP = {
    "Active": ListingStatus.ACTIVE,
    "Inactive": ListingStatus.SOLD,
}

BASE_URL = "https://api.rentcast.io/v1"


class RentcastScraper(BaseScraper):
    SOURCE_NAME = "rentcast"

    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        self.api_key = config.api_key

    def _build_search_params(self, market: str) -> dict:
        """Build Rentcast API query parameters from a market string."""
        parts = market.split(",")
        city = parts[0].strip()
        state = parts[1].strip() if len(parts) > 1 else ""

        params: dict = {
            "city": city,
            "state": state,
            "status": "Active",
            "limit": 500,
        }

        params["price"] = f"{self.search.min_price}:{self.search.max_price}"
        params["bedrooms"] = f"{self.search.min_beds}:{self.search.max_beds}"
        params["bathrooms"] = f"{self.search.min_baths}:"

        prop_types = []
        for pt in self.search.property_types:
            for rc_name, enum_val in _PROPERTY_TYPE_MAP.items():
                if enum_val.value == pt:
                    prop_types.append(rc_name)
        if prop_types:
            params["propertyType"] = ",".join(prop_types)

        return params

    def _parse_listings(self, results: list[dict]) -> list[Listing]:
        """Parse Rentcast API response objects into Listing models."""
        listings: list[Listing] = []

        for item in results:
            try:
                price = item.get("price")
                if not price:
                    continue

                prop_type_str = item.get("propertyType", "")
                prop_type = _PROPERTY_TYPE_MAP.get(prop_type_str, PropertyType.SINGLE_FAMILY)

                status_str = item.get("status", "Active")
                status = _STATUS_MAP.get(status_str, ListingStatus.ACTIVE)

                listing = Listing(
                    source=self.SOURCE_NAME,
                    source_id=str(item.get("id", "")),
                    address=item.get("formattedAddress", ""),
                    city=item.get("city", ""),
                    state=item.get("state", ""),
                    zip_code=str(item.get("zipCode", "")),
                    price=float(price),
                    beds=int(item.get("bedrooms", 0) or 0),
                    baths=float(item.get("bathrooms", 0) or 0),
                    sqft=int(item.get("squareFootage", 0) or 0),
                    lot_sqft=int(item.get("lotSize", 0) or 0),
                    year_built=int(item.get("yearBuilt", 0) or 0),
                    hoa_monthly=float(item.get("hoa", 0) or 0),
                    property_type=prop_type,
                    status=status,
                    days_on_market=int(item.get("daysOnMarket", 0) or 0),
                    tax_annual=float(item.get("propertyTaxes", 0) or 0),
                    raw_data={
                        "latitude": item.get("latitude"),
                        "longitude": item.get("longitude"),
                        "listedDate": item.get("listedDate"),
                        "mlsNumber": item.get("mlsNumber"),
                    },
                )
                listings.append(listing)
            except Exception:
                continue

        return listings

    async def search_market(self, market: str) -> list[Listing]:
        """Search Rentcast for sale listings in a market."""
        if not self.api_key:
            return []

        client = await self._get_client()
        params = self._build_search_params(market)

        resp = await client.get(
            f"{BASE_URL}/listings/sale",
            params=params,
            headers={"X-Api-Key": self.api_key},
        )

        if resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        return self._parse_listings(data)

    async def scrape(self) -> list[Listing]:
        return await self.scrape_all_markets()
