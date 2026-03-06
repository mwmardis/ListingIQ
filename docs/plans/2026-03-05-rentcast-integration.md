# Rentcast Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the broken Zillow scraper with a Rentcast API-backed scraper so the deal scanner returns real property listings.

**Architecture:** A new `RentcastScraper` implements the existing `BaseScraper` interface. It calls the Rentcast Sale Listings API (`GET /v1/listings/sale`), maps response fields to the `Listing` model, and plugs into the existing analysis pipeline with zero changes to the analysis engine or UI rendering logic.

**Tech Stack:** Python 3.10+, httpx (async HTTP), pydantic, pytest + pytest-asyncio

---

### Task 1: Update Config to Support API Key

**Files:**
- Modify: `listingiq/config.py:37-43` (ScraperConfig class)
- Modify: `listingiq/config.py:199-206` (load_config function)
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_scraper_config_has_api_key():
    from listingiq.config import ScraperConfig
    cfg = ScraperConfig()
    assert cfg.api_key == ""


def test_rentcast_api_key_env_override(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key-123")
    from listingiq.config import load_config
    cfg = load_config()
    assert cfg.scraper.api_key == "test-key-123"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_scraper_config_has_api_key tests/test_config.py::test_rentcast_api_key_env_override -v`
Expected: FAIL — `ScraperConfig` has no `api_key` field

**Step 3: Write minimal implementation**

In `listingiq/config.py`, add to `ScraperConfig`:

```python
class ScraperConfig(BaseModel):
    sources: list[str] = ["zillow"]
    interval_minutes: int = 60
    max_concurrency: int = 5
    delay_min: float = 1.0
    delay_max: float = 3.0
    api_key: str = ""
    search: SearchConfig = SearchConfig()
```

In `load_config()`, after the `DATABASE_URL` override block, add:

```python
    rentcast_key = os.environ.get("RENTCAST_API_KEY")
    if rentcast_key:
        cfg.scraper.api_key = rentcast_key
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add listingiq/config.py tests/test_config.py
git commit -m "feat: add api_key to ScraperConfig with RENTCAST_API_KEY env override"
```

---

### Task 2: Create RentcastScraper

**Files:**
- Create: `listingiq/scrapers/rentcast.py`
- Test: `tests/test_scrapers.py`

**Step 1: Write the failing test**

Replace contents of `tests/test_scrapers.py` with:

```python
"""Tests for scraper registry and RentcastScraper."""
import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from listingiq.config import ScraperConfig, SearchConfig
from listingiq.models import Listing, PropertyType, ListingStatus
from listingiq.scrapers import SCRAPERS, get_scraper
from listingiq.scrapers.rentcast import RentcastScraper


# ── Registry Tests ──

class TestScraperRegistry:
    def test_rentcast_is_registered(self):
        assert "rentcast" in SCRAPERS
        assert SCRAPERS["rentcast"] is RentcastScraper

    def test_get_scraper_returns_rentcast(self):
        assert get_scraper("rentcast") is RentcastScraper

    def test_get_scraper_unknown_raises(self):
        with pytest.raises(ValueError):
            get_scraper("redfin")


# ── Sample API Response ──

SAMPLE_LISTING = {
    "id": "rc-123",
    "formattedAddress": "123 Main St, Austin, TX 78701",
    "addressLine1": "123 Main St",
    "city": "Austin",
    "state": "TX",
    "zipCode": "78701",
    "latitude": 30.267,
    "longitude": -97.743,
    "propertyType": "Single Family",
    "bedrooms": 3,
    "bathrooms": 2,
    "squareFootage": 1500,
    "lotSize": 5000,
    "yearBuilt": 1990,
    "hoa": 50.0,
    "status": "Active",
    "price": 350000,
    "listedDate": "2025-01-15",
    "daysOnMarket": 45,
}


# ── RentcastScraper Tests ──

class TestRentcastScraper:
    def _make_scraper(self, api_key="test-key"):
        cfg = ScraperConfig(
            api_key=api_key,
            search=SearchConfig(markets=["Austin, TX"]),
        )
        return RentcastScraper(cfg)

    def test_init_sets_api_key(self):
        scraper = self._make_scraper("my-key")
        assert scraper.api_key == "my-key"

    def test_build_params_basic(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Austin, TX")
        assert params["city"] == "Austin"
        assert params["state"] == "TX"
        assert "price" in params

    def test_build_params_price_range(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Austin, TX")
        assert params["price"] == "50000:500000"

    def test_build_params_bedrooms_range(self):
        scraper = self._make_scraper()
        params = scraper._build_search_params("Austin, TX")
        assert params["bedrooms"] == "2:6"

    def test_parse_listings(self):
        scraper = self._make_scraper()
        listings = scraper._parse_listings([SAMPLE_LISTING])
        assert len(listings) == 1
        listing = listings[0]
        assert listing.source == "rentcast"
        assert listing.source_id == "rc-123"
        assert listing.address == "123 Main St, Austin, TX 78701"
        assert listing.city == "Austin"
        assert listing.state == "TX"
        assert listing.zip_code == "78701"
        assert listing.price == 350000
        assert listing.beds == 3
        assert listing.baths == 2
        assert listing.sqft == 1500
        assert listing.lot_sqft == 5000
        assert listing.year_built == 1990
        assert listing.hoa_monthly == 50.0
        assert listing.days_on_market == 45
        assert listing.property_type == PropertyType.SINGLE_FAMILY
        assert listing.status == ListingStatus.ACTIVE

    def test_parse_listings_skips_no_price(self):
        bad = {**SAMPLE_LISTING, "price": None}
        scraper = self._make_scraper()
        listings = scraper._parse_listings([bad])
        assert len(listings) == 0

    def test_parse_listings_handles_missing_fields(self):
        minimal = {
            "id": "rc-456",
            "price": 200000,
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
        mock_response.json.return_value = [SAMPLE_LISTING]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        scraper._client = mock_client

        listings = await scraper.search_market("Austin, TX")

        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://api.rentcast.io/v1/listings/sale"
        assert call_args[1]["headers"]["X-Api-Key"] == "test-key"
        assert len(listings) == 1

    @pytest.mark.asyncio
    async def test_search_market_returns_empty_on_error(self):
        scraper = self._make_scraper()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        scraper._client = mock_client

        listings = await scraper.search_market("Austin, TX")
        assert listings == []

    @pytest.mark.asyncio
    async def test_search_market_no_api_key_returns_empty(self):
        scraper = self._make_scraper(api_key="")
        listings = await scraper.search_market("Austin, TX")
        assert listings == []
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scrapers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'listingiq.scrapers.rentcast'`

**Step 3: Write the implementation**

Create `listingiq/scrapers/rentcast.py`:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scrapers.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add listingiq/scrapers/rentcast.py tests/test_scrapers.py
git commit -m "feat: add RentcastScraper with sale listings endpoint"
```

---

### Task 3: Update Scraper Registry and Remove Zillow

**Files:**
- Modify: `listingiq/scrapers/__init__.py`
- Delete: `listingiq/scrapers/zillow.py`

**Step 1: Update the registry**

Replace contents of `listingiq/scrapers/__init__.py`:

```python
"""MLS data scrapers for various sources."""

from listingiq.scrapers.base import BaseScraper
from listingiq.scrapers.rentcast import RentcastScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    "rentcast": RentcastScraper,
}


def get_scraper(name: str) -> type[BaseScraper]:
    """Get a scraper class by name."""
    if name not in SCRAPERS:
        raise ValueError(f"Unknown scraper: {name}. Available: {list(SCRAPERS.keys())}")
    return SCRAPERS[name]
```

**Step 2: Delete `listingiq/scrapers/zillow.py`**

```bash
rm listingiq/scrapers/zillow.py
```

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS (no remaining references to zillow)

**Step 4: Commit**

```bash
git add listingiq/scrapers/__init__.py
git rm listingiq/scrapers/zillow.py
git commit -m "feat: replace zillow with rentcast in scraper registry"
```

---

### Task 4: Update Config and UI

**Files:**
- Modify: `config/default.toml:5-6`
- Modify: `listingiq/api/server.py:1246-1248` (source dropdown)

**Step 1: Update default.toml**

Change line 6 from `sources = ["zillow"]` to:

```toml
sources = ["rentcast"]
```

**Step 2: Update the scanner UI dropdown**

In `listingiq/api/server.py`, find the source `<select>` (around line 1246) and replace:

```html
<select id="source">
    <option value="rentcast">Rentcast</option>
</select>
```

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add config/default.toml listingiq/api/server.py
git commit -m "feat: update config and UI to use rentcast source"
```

---

### Task 5: Remove Unused Dependencies

**Files:**
- Modify: `pyproject.toml:13-14` (remove beautifulsoup4 and lxml)

**Step 1: Remove beautifulsoup4 and lxml from dependencies**

These were only used by the Zillow scraper. Remove them from the `dependencies` list in `pyproject.toml`.

**Step 2: Verify no remaining imports**

Run: `grep -r "beautifulsoup\|from bs4\|import lxml" listingiq/`
Expected: No output (no remaining references)

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: remove beautifulsoup4 and lxml deps (zillow scraper removed)"
```

---

### Task 6: Final Verification

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 2: Verify the server starts**

Run: `python -c "from listingiq.api.server import app; print('Server imports OK')"`
Expected: "Server imports OK"

**Step 3: Grep for any remaining zillow references**

Run: `grep -ri "zillow" listingiq/ config/ tests/`
Expected: No output
