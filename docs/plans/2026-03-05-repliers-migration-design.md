# Replace Rentcast with Repliers API

**Date:** 2026-03-05
**Approach:** Drop-in replacement (same pattern as Zillow → Rentcast migration)

## Summary

Replace the Rentcast API scraper with Repliers API to reduce costs. Same `BaseScraper` interface, minimal changes outside the scraper layer. New feature: search both sale and lease listings.

## New Scraper: `RepliersScraper`

**Endpoint:** `GET https://api.repliers.io/listings`
**Auth header:** `REPLIERS-API-KEY: <key>`

### Parameter Mapping

| Config Field | Repliers Param |
|---|---|
| market "Houston, TX" | `city=["Houston"]`, `state=["TX"]` |
| `min_price` / `max_price` | `minPrice` / `maxPrice` |
| `min_beds` / `max_beds` | `minBedroomsTotal` / `maxBedroomsTotal` |
| `min_baths` / `max_baths` | `minBaths` / `maxBaths` |
| property_types | `class` + `propertyType` mapping |
| sale + lease | `type=["sale","lease"]` |
| cap 500 | `resultsPerPage=500` |
| active only | `status=["A"]` |

### Response Field Mapping

| Repliers Field | Listing Model Field |
|---|---|
| `mlsNumber` | `source_id` |
| `address.streetNumber + streetName + streetSuffix` | `address` |
| `address.city` | `city` |
| `address.state` | `state` |
| `address.zip` | `zip_code` |
| `listPrice` | `price` |
| `details.numBedrooms` + `numBedroomsPlus` | `beds` |
| `details.numBathrooms` | `baths` |
| `details.sqft` | `sqft` |
| `lot.size` or `lot.acres` | `lot_sqft` |
| `details.yearBuilt` | `year_built` |
| `condominium.fees.maintenance` | `hoa_monthly` |
| `details.propertyType` | `property_type` (enum) |
| `status` A→ACTIVE, U→SOLD | `status` |
| `daysOnMarket` | `days_on_market` |
| `taxes.annualAmount` | `tax_annual` |
| lat, long, listDate, type | `raw_data` |

## Config Changes

- `ScraperConfig.sources` default: `["repliers"]`
- `SearchConfig.markets` default: `["Houston, TX"]`
- Env var: `RENTCAST_API_KEY` → `REPLIERS_API_KEY`
- `default.toml`: `sources = ["repliers"]`

## File Changes

| Action | File |
|---|---|
| Delete | `listingiq/scrapers/rentcast.py` |
| Create | `listingiq/scrapers/repliers.py` |
| Modify | `listingiq/scrapers/__init__.py` |
| Modify | `listingiq/config.py` |
| Modify | `config/default.toml` |
| Modify | `tests/test_scrapers.py` |
| Modify | `tests/test_config.py` |

## Tests

- `test_init_sets_api_key` — key stored on instance
- `test_build_params_basic` — "Houston, TX" → city/state arrays
- `test_build_params_price_range` — minPrice/maxPrice mapped
- `test_build_params_includes_type` — type=["sale","lease"]
- `test_parse_listings` — full field mapping with sample response
- `test_parse_listings_skips_no_price` — no listPrice → filtered
- `test_parse_listings_handles_missing_fields` — sparse data handled
- `test_search_market_calls_api` — correct endpoint + header
- `test_search_market_returns_empty_on_error` — non-200 → []
- `test_search_market_no_api_key_returns_empty` — empty key → []
- `test_repliers_api_key_env_override` — env var overrides config
