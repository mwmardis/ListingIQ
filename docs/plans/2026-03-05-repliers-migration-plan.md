# Repliers Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Rentcast API scraper with Repliers API to reduce costs, adding sale+lease search.

**Architecture:** Drop-in replacement of `RentcastScraper` with `RepliersScraper`, same `BaseScraper` interface. Config defaults change to `repliers` source and `Houston, TX` market. Env var changes from `RENTCAST_API_KEY` to `REPLIERS_API_KEY`.

**Tech Stack:** Python 3.10+, httpx (async HTTP), pydantic, pytest + pytest-asyncio

---

### Task 1: Update Config Defaults

**Files:**
- Modify: `listingiq/config.py:27` (SearchConfig.markets default)
- Modify: `listingiq/config.py:38` (ScraperConfig.sources default)
- Modify: `listingiq/config.py:207-209` (env var name)
- Modify: `config/default.toml:5-6` (sources and comment)
- Modify: `config/default.toml:17` (markets)
- Modify: `tests/test_config.py:41-45` (env var test)

**Step 1: Update `listingiq/config.py`**

Change line 27:
```python
markets: list[str] = ["Houston, TX"]
```

Change line 38:
```python
sources: list[str] = ["repliers"]
```

Change lines 207-209:
```python
repliers_key = os.environ.get("REPLIERS_API_KEY")
if repliers_key:
    cfg.scraper.api_key = repliers_key
```

**Step 2: Update `config/default.toml`**

Change lines 4-6:
```toml
[scraper]
# Source to scrape: "repliers"
sources = ["repliers"]
```

Change line 17:
```toml
markets = ["Houston, TX"]
```

**Step 3: Update `tests/test_config.py`**

Replace `test_rentcast_api_key_env_override` (lines 41-45):
```python
def test_repliers_api_key_env_override(monkeypatch):
    monkeypatch.setenv("REPLIERS_API_KEY", "test-key-123")
    from listingiq.config import load_config
    cfg = load_config()
    assert cfg.scraper.api_key == "test-key-123"
```

**Step 4: Run config tests**

Run: `python -m pytest tests/test_config.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add listingiq/config.py config/default.toml tests/test_config.py
git commit -m "feat: update config defaults for Repliers API migration"
```

---

### Task 2: Write Failing Tests for RepliersScraper

**Files:**
- Rewrite: `tests/test_scrapers.py`

**Step 1: Write the test file**

Replace entire contents of `tests/test_scrapers.py`:

```python
"""Tests for scraper registry and RepliersScraper."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from listingiq.config import ScraperConfig, SearchConfig
from listingiq.models import PropertyType, ListingStatus
from listingiq.scrapers.repliers import RepliersScraper


# ── Sample API Response ──

SAMPLE_LISTING = {
    "mlsNumber": "H1234567",
    "resource": "Property",
    "status": "A",
    "class": "residential",
    "type": "sale",
    "listPrice": "350000",
    "listDate": "2025-01-15T00:00:00Z",
    "lastStatus": "New",
    "soldPrice": None,
    "soldDate": None,
    "originalPrice": "360000",
    "address": {
        "area": "Houston",
        "city": "Houston",
        "country": "US",
        "district": "Downtown",
        "neighborhood": "Midtown",
        "streetDirection": "",
        "streetName": "Main",
        "streetNumber": "123",
        "streetSuffix": "St",
        "unitNumber": None,
        "zip": "77001",
        "state": "Texas",
    },
    "map": {
        "latitude": "29.7604",
        "longitude": "-95.3698",
    },
    "details": {
        "numBedrooms": "3",
        "numBedroomsPlus": None,
        "numBathrooms": "2",
        "sqft": "1500",
        "propertyType": "Detached",
        "style": "2-Storey",
        "yearBuilt": "1990",
        "numGarageSpaces": "2",
        "numParkingSpaces": "4",
    },
    "lot": {
        "acres": "0.25",
        "depth": "100",
        "width": "50",
        "size": None,
    },
    "condominium": {
        "fees": {
            "maintenance": "50",
        },
    },
    "taxes": {
        "annualAmount": "4500",
    },
    "daysOnMarket": "45",
    "images": [
        "https://cdn.repliers.io/image1.jpg",
        "https://cdn.repliers.io/image2.jpg",
    ],
    "photoCount": 2,
}


# ── RepliersScraper Tests ──


class TestRepliersScraper:
    def _make_scraper(self, api_key="test-key"):
        cfg = ScraperConfig(
            api_key=api_key,
            search=SearchConfig(markets=["Houston, TX"]),
        )
        return RepliersScraper(cfg)

    def test_init_sets_api_key(self):
        scraper = self._make_scraper("my-key")
        assert scraper.api_key == "my-key"

    def test_build_params_basic(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["city"] == "Houston"
        assert params["state"] == "TX"
        assert params["status"] == "A"
        assert params["resultsPerPage"] == 500

    def test_build_params_price_range(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["minPrice"] == 50000
        assert params["maxPrice"] == 500000

    def test_build_params_bedrooms(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["minBedroomsTotal"] == 2
        assert params["maxBedroomsTotal"] == 6

    def test_build_params_bathrooms(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert params["minBaths"] == 1
        assert params["maxBaths"] == 4

    def test_build_params_includes_type(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Houston, TX")
        assert "sale" in params["type"]
        assert "lease" in params["type"]

    def test_parse_listings(self):
        scraper = self._make_scraper()
        listings = scraper._parse_listings([SAMPLE_LISTING])
        assert len(listings) == 1
        listing = listings[0]
        assert listing.source == "repliers"
        assert listing.source_id == "H1234567"
        assert listing.address == "123 Main St"
        assert listing.city == "Houston"
        assert listing.state == "Texas"
        assert listing.zip_code == "77001"
        assert listing.price == 350000.0
        assert listing.beds == 3
        assert listing.baths == 2.0
        assert listing.sqft == 1500
        assert listing.year_built == 1990
        assert listing.hoa_monthly == 50.0
        assert listing.days_on_market == 45
        assert listing.tax_annual == 4500.0
        assert listing.property_type == PropertyType.SINGLE_FAMILY
        assert listing.status == ListingStatus.ACTIVE
        assert listing.raw_data["latitude"] == "29.7604"
        assert listing.raw_data["longitude"] == "-95.3698"
        assert listing.raw_data["type"] == "sale"

    def test_parse_listings_lot_sqft_from_acres(self):
        scraper = self._make_scraper()
        listings = scraper._parse_listings([SAMPLE_LISTING])
        # 0.25 acres * 43560 sqft/acre = 10890
        assert listings[0].lot_sqft == 10890

    def test_parse_listings_skips_no_price(self):
        bad = {**SAMPLE_LISTING, "listPrice": None}
        scraper = self._make_scraper()
        listings = scraper._parse_listings([bad])
        assert len(listings) == 0

    def test_parse_listings_handles_missing_fields(self):
        minimal = {
            "mlsNumber": "H9999999",
            "listPrice": "200000",
        }
        scraper = self._make_scraper()
        listings = scraper._parse_listings([minimal])
        assert len(listings) == 1
        assert listings[0].price == 200000
        assert listings[0].beds == 0
        assert listings[0].sqft == 0

    @pytest.mark.asyncio
    async def test_search_market_calls_api(self):
        scraper = self._make_scraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "page": 1,
            "numPages": 1,
            "count": 1,
            "listings": [SAMPLE_LISTING],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        scraper._client = mock_client

        listings = await scraper.search_market("Houston, TX")

        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://api.repliers.io/listings"
        assert call_args[1]["headers"]["REPLIERS-API-KEY"] == "test-key"
        assert len(listings) == 1

    @pytest.mark.asyncio
    async def test_search_market_returns_empty_on_error(self):
        scraper = self._make_scraper()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        scraper._client = mock_client

        listings = await scraper.search_market("Houston, TX")
        assert listings == []

    @pytest.mark.asyncio
    async def test_search_market_no_api_key_returns_empty(self):
        scraper = self._make_scraper(api_key="")
        listings = await scraper.search_market("Houston, TX")
        assert listings == []
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scrapers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'listingiq.scrapers.repliers'`

**Step 3: Commit failing tests**

```bash
git add tests/test_scrapers.py
git commit -m "test: add failing tests for RepliersScraper"
```

---

### Task 3: Implement RepliersScraper

**Files:**
- Create: `listingiq/scrapers/repliers.py`

**Step 1: Create the scraper**

Create `listingiq/scrapers/repliers.py`:

```python
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
```

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_scrapers.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add listingiq/scrapers/repliers.py
git commit -m "feat: add RepliersScraper implementation"
```

---

### Task 4: Update Registry and Delete Rentcast

**Files:**
- Modify: `listingiq/scrapers/__init__.py`
- Delete: `listingiq/scrapers/rentcast.py`

**Step 1: Update the registry**

Replace entire contents of `listingiq/scrapers/__init__.py`:

```python
"""MLS data scrapers for various sources."""

from listingiq.scrapers.base import BaseScraper
from listingiq.scrapers.repliers import RepliersScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    "repliers": RepliersScraper,
}


def get_scraper(name: str) -> type[BaseScraper]:
    """Get a scraper class by name."""
    if name not in SCRAPERS:
        raise ValueError(f"Unknown scraper: {name}. Available: {list(SCRAPERS.keys())}")
    return SCRAPERS[name]
```

**Step 2: Delete rentcast.py**

```bash
git rm listingiq/scrapers/rentcast.py
```

**Step 3: Run all tests**

Run: `python -m pytest -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add listingiq/scrapers/__init__.py
git commit -m "feat: replace Rentcast with Repliers in scraper registry"
```

---

### Task 5: Final Verification

**Step 1: Run full test suite**

Run: `python -m pytest -v`
Expected: All PASS, no import errors, no references to rentcast in test output

**Step 2: Grep for stale rentcast references**

Run: `grep -ri "rentcast" listingiq/ tests/ config/ --include="*.py" --include="*.toml"`
Expected: No matches (all references should be gone)

**Step 3: Commit design docs**

```bash
git add docs/plans/
git commit -m "docs: add Repliers migration design and implementation plan"
```
