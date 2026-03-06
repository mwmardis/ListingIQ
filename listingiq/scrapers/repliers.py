"""Repliers API scraper implementation.

Uses the Repliers Listings API to fetch active property listings
for investment analysis. Searches both sale and lease listings.
"""

from __future__ import annotations

from listingiq.config import ScraperConfig
from listingiq.models import Listing, PropertyType, ListingStatus
from listingiq.scrapers.base import BaseScraper

_PROPERTY_TYPE_MAP = {
    "Detached": PropertyType.SINGLE_FAMILY,
    "Semi-Detached": PropertyType.SINGLE_FAMILY,
    "Att/Row/Twnhouse": PropertyType.TOWNHOUSE,
    "Townhouse": PropertyType.TOWNHOUSE,
    "Condo Apt": PropertyType.CONDO,
    "Condo Townhouse": PropertyType.CONDO,
    "Multiplex": PropertyType.MULTI_FAMILY,
    "Duplex": PropertyType.MULTI_FAMILY,
    "Triplex": PropertyType.MULTI_FAMILY,
    "Fourplex": PropertyType.MULTI_FAMILY,
}

_STATUS_MAP = {
    "A": ListingStatus.ACTIVE,
    "U": ListingStatus.SOLD,
}

BASE_URL = "https://api.repliers.io"

_SQFT_PER_ACRE = 43560


class RepliersScraper(BaseScraper):
    SOURCE_NAME = "repliers"

    def __init__(self, config: ScraperConfig):
        super().__init__(config)
        self.api_key = config.api_key

    def _build_search_params(self, market: str) -> dict:
        """Build Repliers API query parameters from a market string."""
        parts = market.split(",")
        city = parts[0].strip()
        state = parts[1].strip() if len(parts) > 1 else ""

        params: dict = {
            "city": city,
            "state": state,
            "status": "A",
            "type": "sale,lease",
            "resultsPerPage": 500,
        }

        params["minPrice"] = self.search.min_price
        params["maxPrice"] = self.search.max_price
        params["minBedroomsTotal"] = self.search.min_beds
        params["maxBedroomsTotal"] = self.search.max_beds
        params["minBaths"] = self.search.min_baths
        params["maxBaths"] = self.search.max_baths

        return params

    def _parse_listings(self, results: list[dict]) -> list[Listing]:
        """Parse Repliers API listing objects into Listing models."""
        listings: list[Listing] = []

        for item in results:
            try:
                list_price = item.get("listPrice")
                if not list_price:
                    continue

                address_data = item.get("address") or {}
                details = item.get("details") or {}
                lot_data = item.get("lot") or {}
                condo_data = item.get("condominium") or {}
                condo_fees = condo_data.get("fees") or {}
                taxes_data = item.get("taxes") or {}
                map_data = item.get("map") or {}

                # Build address string
                parts = [
                    address_data.get("streetNumber", ""),
                    address_data.get("streetName", ""),
                    address_data.get("streetSuffix", ""),
                ]
                address_str = " ".join(p for p in parts if p).strip()

                # Property type mapping
                prop_type_str = details.get("propertyType", "")
                prop_type = _PROPERTY_TYPE_MAP.get(
                    prop_type_str, PropertyType.SINGLE_FAMILY
                )

                # Status mapping
                status_str = item.get("status", "A")
                status = _STATUS_MAP.get(status_str, ListingStatus.ACTIVE)

                # Lot sqft: prefer size, fall back to acres conversion
                lot_sqft = 0
                lot_size = lot_data.get("size")
                if lot_size:
                    try:
                        lot_sqft = int(float(lot_size))
                    except (ValueError, TypeError):
                        pass
                if not lot_sqft:
                    acres = lot_data.get("acres")
                    if acres:
                        try:
                            lot_sqft = int(float(acres) * _SQFT_PER_ACRE)
                        except (ValueError, TypeError):
                            pass

                listing = Listing(
                    source=self.SOURCE_NAME,
                    source_id=str(item.get("mlsNumber", "")),
                    address=address_str,
                    city=address_data.get("city", ""),
                    state=address_data.get("state", ""),
                    zip_code=str(address_data.get("zip", "")),
                    price=float(list_price),
                    beds=int(details.get("numBedrooms", 0) or 0),
                    baths=float(details.get("numBathrooms", 0) or 0),
                    sqft=int(float(details.get("sqft", 0) or 0)),
                    lot_sqft=lot_sqft,
                    year_built=int(details.get("yearBuilt", 0) or 0),
                    hoa_monthly=float(condo_fees.get("maintenance", 0) or 0),
                    property_type=prop_type,
                    status=status,
                    days_on_market=int(item.get("daysOnMarket", 0) or 0),
                    tax_annual=float(taxes_data.get("annualAmount", 0) or 0),
                    raw_data={
                        "latitude": map_data.get("latitude"),
                        "longitude": map_data.get("longitude"),
                        "listDate": item.get("listDate"),
                        "type": item.get("type"),
                    },
                )
                listings.append(listing)
            except Exception:
                continue

        return listings

    async def search_market(self, market: str) -> list[Listing]:
        """Search Repliers for listings in a market."""
        if not self.api_key:
            return []

        client = await self._get_client()
        params = self._build_search_params(market)

        resp = await client.get(
            f"{BASE_URL}/listings",
            params=params,
            headers={"REPLIERS-API-KEY": self.api_key},
        )

        if resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        results = data.get("listings", [])
        if not isinstance(results, list):
            return []

        return self._parse_listings(results)

    async def scrape(self) -> list[Listing]:
        return await self.scrape_all_markets()
