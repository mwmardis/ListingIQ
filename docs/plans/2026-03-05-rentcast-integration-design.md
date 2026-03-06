# Rentcast API Integration Design

**Date:** 2026-03-05
**Status:** Approved

## Problem

The deal scanner returns no properties because the Zillow scraper is blocked by Zillow's bot detection. We need a reliable, API-based data source.

## Solution

Replace the Zillow scraper with a Rentcast API-backed scraper using a drop-in replacement approach.

## Approach: Drop-in Scraper Replacement

Create a `RentcastScraper` that implements `BaseScraper`, replacing the Zillow scraper entirely. Uses the Rentcast **Sale Listings** endpoint (`GET /v1/listings/sale`) for the deal scanner.

### API Endpoints

| Endpoint | Purpose | Ships in this change |
|---|---|---|
| `GET /v1/listings/sale` | Powers `search_market()` in deal scanner | Yes |
| `GET /v1/avm/rent/long-term` | Rent estimate enrichment | Future |
| `GET /v1/avm/value` | ARV estimate enrichment | Future |

### Field Mapping (Rentcast → Listing model)

| Rentcast Field | Listing Field |
|---|---|
| `formattedAddress` | `address` |
| `city` | `city` |
| `state` | `state` |
| `zipCode` | `zip_code` |
| `price` | `price` |
| `bedrooms` | `beds` |
| `bathrooms` | `baths` |
| `squareFootage` | `sqft` |
| `lotSize` | `lot_sqft` |
| `yearBuilt` | `year_built` |
| `propertyType` | `property_type` (mapped via enum) |
| `status` | `status` (Active→active, Inactive→sold) |
| `daysOnMarket` | `days_on_market` |
| `id` | `source_id` |
| `hoa` | `hoa_monthly` |

### Search Parameter Mapping (SearchConfig → Rentcast)

| SearchConfig | Rentcast Param | Format |
|---|---|---|
| `markets` (e.g. "Austin, TX") | `city` + `state` | Parsed from "City, ST" |
| `min_price` / `max_price` | `price` | Range: "min:max" |
| `min_beds` / `max_beds` | `bedrooms` | Range: "min:max" |
| `min_baths` | `bathrooms` | Range: "min:" |
| `property_types` | `propertyType` | Mapped enum names |

### API Key Configuration

- Environment variable: `RENTCAST_API_KEY`
- Base URL: `https://api.rentcast.io/v1`
- Auth header: `X-Api-Key: <key>`
- Rate limit: 20 req/s (existing delay mechanism handles this)
- Free tier: 50 calls/month

### Files Changed

1. **`listingiq/scrapers/rentcast.py`** — new `RentcastScraper` class
2. **`listingiq/scrapers/__init__.py`** — register `"rentcast"`, remove `"zillow"`
3. **`listingiq/scrapers/zillow.py`** — deleted
4. **`config/default.toml`** — change `sources = ["rentcast"]`
5. **`listingiq/config.py`** — add `api_key` to `ScraperConfig`, allow `RENTCAST_API_KEY` env var override
6. **`listingiq/api/server.py`** — update scanner UI dropdown to show "rentcast" instead of "zillow"
7. **`tests/test_scrapers.py`** — update tests for Rentcast

### Future Work

- Integrate rent estimate endpoint for better cash flow analysis
- Integrate value estimate endpoint for better ARV/flip analysis
- Add caching layer to reduce API call consumption
