"""Sales comp service for estimating After Repair Value (ARV).

Searches for recently sold comparable properties and calculates an
adjusted ARV based on the subject property's characteristics.
"""

from __future__ import annotations

import json
import logging
from statistics import median

import httpx

from listingiq.config import CompsConfig
from listingiq.models import Listing, SalesComp

logger = logging.getLogger(__name__)


class SalesCompService:
    """Estimates ARV using recently sold comparable properties.

    Uses Redfin's sold listing data to find comparable sales, then
    adjusts the median sold price based on property differences.
    Falls back to a percentage-based estimate when no comps are found.
    """

    REDFIN_AUTOCOMPLETE = "https://www.redfin.com/stingray/do/location-autocomplete"
    REDFIN_GIS = "https://www.redfin.com/stingray/api/gis"

    def __init__(self, comps_config: CompsConfig):
        self.cfg = comps_config
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

    async def estimate_arv(self, listing: Listing) -> tuple[float, list[SalesComp], str]:
        """Estimate After Repair Value from sold comps.

        Returns:
            Tuple of (estimated_arv, sales_comps, confidence).
        """
        comps: list[SalesComp] = []

        try:
            comps = await self._fetch_sold_comps(listing)
        except Exception as e:
            logger.warning("Failed to fetch sales comps: %s", e)

        if len(comps) >= self.cfg.min_comps_for_high_confidence:
            confidence = "high"
            arv = self._calculate_arv_from_comps(comps, listing)
        elif len(comps) >= self.cfg.min_comps_for_medium_confidence:
            confidence = "medium"
            arv = self._calculate_arv_from_comps(comps, listing)
        else:
            confidence = "low"
            if comps:
                # Blend comp-based and formula-based
                comp_arv = self._calculate_arv_from_comps(comps, listing)
                formula_arv = self._estimate_arv_formula(listing)
                arv = comp_arv * 0.6 + formula_arv * 0.4
            else:
                arv = self._estimate_arv_formula(listing)

        return round(arv, 2), comps, confidence

    async def _fetch_sold_comps(self, listing: Listing) -> list[SalesComp]:
        """Fetch recently sold properties from Redfin."""
        client = await self._get_client()

        market = f"{listing.city}, {listing.state}" if listing.city else None
        if not market:
            return []

        # Resolve market
        resp = await client.get(
            self.REDFIN_AUTOCOMPLETE,
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

        # Search for recently sold listings
        params = {
            "al": 1,
            "region_id": region["region_id"],
            "region_type": region["region_type"],
            "num_homes": 100,
            "sf": "1,2,3,5,6,7",
            "status": 9,  # sold
            "sold_within_days": self.cfg.sales_max_age_days,
            "v": 8,
        }

        # Filter by similar bed count
        if listing.beds > 0:
            params["min_num_beds"] = max(1, listing.beds - self.cfg.sales_beds_tolerance)
            params["max_num_beds"] = listing.beds + self.cfg.sales_beds_tolerance

        resp = await client.get(self.REDFIN_GIS, params=params)
        if resp.status_code != 200:
            return []

        text = resp.text
        if text.startswith("{}&&"):
            text = text[4:]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        comps: list[SalesComp] = []
        for home in data.get("payload", {}).get("homes", []):
            try:
                sold_price = home.get("price", {}).get("value", 0)
                if not sold_price:
                    continue

                sqft = home.get("sqFt", {}).get("value", 0) or 0

                # Filter by sqft similarity
                if listing.sqft > 0 and sqft > 0:
                    sqft_diff = abs(sqft - listing.sqft) / listing.sqft
                    if sqft_diff > self.cfg.sales_sqft_tolerance:
                        continue

                ppsf = sold_price / sqft if sqft > 0 else 0

                comp = SalesComp(
                    address=home.get("streetLine", {}).get("value", "Unknown"),
                    sold_price=sold_price,
                    sold_date=home.get("soldDate", ""),
                    beds=home.get("beds", 0) or 0,
                    baths=home.get("baths", 0) or 0,
                    sqft=sqft,
                    price_per_sqft=round(ppsf, 2),
                    source="redfin",
                )
                comps.append(comp)
            except Exception:
                continue

        # Sort by most relevant (closest sqft match first)
        if listing.sqft > 0:
            comps.sort(key=lambda c: abs(c.sqft - listing.sqft) if c.sqft > 0 else float("inf"))

        return comps[: self.cfg.sales_max_comps]

    def _calculate_arv_from_comps(self, comps: list[SalesComp], listing: Listing) -> float:
        """Calculate ARV by adjusting comp prices to match subject property."""
        if not comps:
            return 0.0

        # Use price-per-sqft method when sqft data is available
        comps_with_ppsf = [c for c in comps if c.price_per_sqft > 0]

        if comps_with_ppsf and listing.sqft > 0:
            # Median price per sqft from comps, applied to subject's sqft
            median_ppsf = median(c.price_per_sqft for c in comps_with_ppsf)
            arv = median_ppsf * listing.sqft

            # Adjust for bedroom difference (comp median beds vs subject)
            comp_median_beds = median(c.beds for c in comps_with_ppsf) if comps_with_ppsf else listing.beds
            bed_diff = listing.beds - comp_median_beds
            # Each bedroom is worth roughly 5-8% of home value
            arv *= 1 + (bed_diff * 0.06)

            # Adjust for bathroom difference
            comp_median_baths = median(c.baths for c in comps_with_ppsf) if comps_with_ppsf else listing.baths
            bath_diff = listing.baths - comp_median_baths
            arv *= 1 + (bath_diff * 0.03)

            return arv

        # Fallback: median sold price directly
        return median(c.sold_price for c in comps)

    def _estimate_arv_formula(self, listing: Listing) -> float:
        """Fallback ARV estimation when no sold comps are available.

        Uses the property's current price and typical rehab value-add ratios.
        This is less accurate than comp-based estimates but better than nothing.
        """
        # Assume a rehab can add 20-40% value depending on property age and type
        base = listing.price
        if listing.year_built > 0:
            age = 2026 - listing.year_built
            if age > 40:
                multiplier = 1.40  # older homes have more upside
            elif age > 20:
                multiplier = 1.30
            elif age > 10:
                multiplier = 1.20
            else:
                multiplier = 1.10  # newer homes, less rehab upside
        else:
            multiplier = 1.30  # default

        return base * multiplier

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
