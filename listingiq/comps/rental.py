"""Rental comp service for estimating market rent.

Uses a multi-factor estimation model that considers property characteristics
and local market data. Can be extended with scraping-based rental comp sources.
"""

from __future__ import annotations

import json
import logging
from statistics import median

import httpx

from listingiq.config import CompsConfig, ScraperConfig
from listingiq.models import Listing, RentalComp

logger = logging.getLogger(__name__)

# Base monthly rent per bedroom by market tier (fallback when no comps)
_BASE_RENT_PER_BED = {
    "high": 900,   # SF, NYC, LA, Seattle, Boston
    "medium": 650,  # Austin, Denver, Nashville, Portland
    "low": 475,     # Memphis, Cleveland, Indianapolis, Birmingham
}

_HIGH_COST_MARKETS = {
    "san francisco", "new york", "los angeles", "seattle", "boston",
    "san diego", "san jose", "washington", "miami",
}
_LOW_COST_MARKETS = {
    "memphis", "cleveland", "indianapolis", "birmingham", "detroit",
    "st louis", "kansas city", "columbus", "jacksonville", "san antonio",
}


class RentalCompService:
    """Estimates market rent using comparable rental data and multi-factor models.

    Two estimation approaches, used in priority order:
    1. Scraped rental comps from Redfin's rental search (if available)
    2. Multi-factor formula using property characteristics and market data
    """

    def __init__(self, comps_config: CompsConfig, scraper_config: ScraperConfig | None = None):
        self.cfg = comps_config
        self.scraper_cfg = scraper_config
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
                },
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def estimate_rent(self, listing: Listing) -> tuple[float, list[RentalComp], str]:
        """Estimate monthly rent for a listing.

        Returns:
            Tuple of (estimated_rent, rental_comps, confidence).
            confidence is "low", "medium", or "high".
        """
        comps: list[RentalComp] = []
        confidence = "low"

        # Try scraping rental comps from Redfin
        if self.scraper_cfg:
            try:
                comps = await self._scrape_rental_comps(listing)
            except Exception as e:
                logger.warning("Failed to scrape rental comps: %s", e)

        if len(comps) >= self.cfg.min_comps_for_high_confidence:
            confidence = "high"
            rent = self._median_rent_from_comps(comps, listing)
        elif len(comps) >= self.cfg.min_comps_for_medium_confidence:
            confidence = "medium"
            rent = self._median_rent_from_comps(comps, listing)
        else:
            # Fall back to multi-factor estimation
            confidence = "low" if not comps else "medium"
            formula_rent = self._estimate_rent_formula(listing)
            if comps:
                # Blend: weight comp data more heavily
                comp_rent = self._median_rent_from_comps(comps, listing)
                rent = comp_rent * 0.7 + formula_rent * 0.3
            else:
                rent = formula_rent

        return round(rent, 2), comps, confidence

    async def _scrape_rental_comps(self, listing: Listing) -> list[RentalComp]:
        """Scrape rental listings from Redfin for comparable rentals."""
        client = await self._get_client()

        # Use Redfin's rental search API
        market = f"{listing.city}, {listing.state}" if listing.city else None
        if not market:
            return []

        # Resolve market to region
        resp = await client.get(
            "https://www.redfin.com/stingray/do/location-autocomplete",
            params={"location": market, "v": 2},
        )
        if resp.status_code != 200:
            return []

        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        region = None
        for section in data.get("payload", {}).get("sections", []):
            for row in section.get("rows", []):
                if row.get("type") == "2":
                    region = {"region_id": row.get("id"), "region_type": row.get("type")}
                    break
            if region:
                break

        if not region:
            return []

        # Search for rental listings
        params = {
            "al": 1,
            "region_id": region["region_id"],
            "region_type": region["region_type"],
            "num_homes": 50,
            "sf": "1,2,3,5,6,7",
            "status": 1,
            "is_rental": 1,
            "v": 8,
        }

        # Filter to similar properties
        if listing.beds > 0:
            params["min_num_beds"] = max(1, listing.beds - self.cfg.rental_beds_tolerance)
            params["max_num_beds"] = listing.beds + self.cfg.rental_beds_tolerance

        resp = await client.get("https://www.redfin.com/stingray/api/gis", params=params)
        if resp.status_code != 200:
            return []

        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        comps: list[RentalComp] = []
        for home in data.get("payload", {}).get("homes", []):
            try:
                rent_price = home.get("price", {}).get("value", 0)
                if not rent_price or rent_price > 10_000:  # filter outliers
                    continue

                comp = RentalComp(
                    address=home.get("streetLine", {}).get("value", "Unknown"),
                    monthly_rent=rent_price,
                    beds=home.get("beds", 0) or 0,
                    baths=home.get("baths", 0) or 0,
                    sqft=home.get("sqFt", {}).get("value", 0) or 0,
                    source="redfin",
                )
                comps.append(comp)
            except Exception:
                continue

        # Limit to max comps
        return comps[: self.cfg.rental_max_comps]

    def _median_rent_from_comps(self, comps: list[RentalComp], listing: Listing) -> float:
        """Calculate estimated rent from comps, adjusting for size differences."""
        if not comps:
            return 0.0

        adjusted_rents: list[float] = []
        for comp in comps:
            rent = comp.monthly_rent

            # Adjust for sqft difference if both have sqft data
            if comp.sqft > 0 and listing.sqft > 0:
                sqft_ratio = listing.sqft / comp.sqft
                # Dampen the adjustment (rent doesn't scale 1:1 with size)
                adjustment = 1 + (sqft_ratio - 1) * 0.5
                rent *= adjustment

            # Adjust for bedroom difference
            bed_diff = listing.beds - comp.beds
            rent += bed_diff * 75  # ~$75/mo per bedroom

            adjusted_rents.append(rent)

        return median(adjusted_rents)

    def _estimate_rent_formula(self, listing: Listing) -> float:
        """Multi-factor rent estimation when no comps are available.

        Better than a flat percentage of price because it considers:
        - Property size (sqft)
        - Bedroom count
        - Property type
        - Market tier
        """
        # Determine market tier
        city_lower = listing.city.lower().strip() if listing.city else ""
        if city_lower in _HIGH_COST_MARKETS:
            tier = "high"
        elif city_lower in _LOW_COST_MARKETS:
            tier = "low"
        else:
            tier = "medium"

        # Method 1: Per-sqft rent by property type
        sqft_rates = {
            "single_family": self.cfg.rent_per_sqft_single_family,
            "multi_family": self.cfg.rent_per_sqft_multi_family,
            "condo": self.cfg.rent_per_sqft_condo,
            "townhouse": self.cfg.rent_per_sqft_townhouse,
        }
        rent_per_sqft = sqft_rates.get(listing.property_type.value, 1.10)

        # Adjust for market tier
        tier_multipliers = {"high": 1.6, "medium": 1.0, "low": 0.7}
        rent_per_sqft *= tier_multipliers[tier]

        sqft_estimate = listing.sqft * rent_per_sqft if listing.sqft > 0 else 0

        # Method 2: Per-bedroom rent
        base_per_bed = _BASE_RENT_PER_BED[tier]
        bed_estimate = listing.beds * base_per_bed if listing.beds > 0 else 0

        # Blend methods (prefer sqft-based when sqft is known)
        if sqft_estimate > 0 and bed_estimate > 0:
            rent = sqft_estimate * 0.65 + bed_estimate * 0.35
        elif sqft_estimate > 0:
            rent = sqft_estimate
        elif bed_estimate > 0:
            rent = bed_estimate
        else:
            # Ultimate fallback: 0.8% of price (same as old method)
            rent = listing.price * 0.008

        # Apply age discount for older properties
        if listing.year_built > 0:
            age = 2026 - listing.year_built
            if age > 50:
                rent *= 0.90
            elif age > 30:
                rent *= 0.95

        return max(rent, 0)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
