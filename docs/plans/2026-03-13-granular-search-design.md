# Granular Search: Zip Codes & Neighborhoods

**Date:** 2026-03-13
**Status:** Approved

## Problem

The dashboard search only accepts broad metro strings like "Houston, TX". Zillow returns ~40 listings for the whole metro, which is too coarse for targeted investing in specific zip codes or neighborhoods.

## Solution

URL-based search targeting. Zillow encodes search areas in its URL structure. We convert user input (zip codes, neighborhood names) into the correct Zillow URL slug and scrape that page directly.

## Search Input

The Market Scanner search bar accepts three formats:

| Input Type | Example | Zillow URL |
|------------|---------|-----------|
| Metro | `Houston, TX` | `/houston-tx/` |
| Zip code | `77084` | `/houston-tx/77084/` |
| Neighborhood | `Spring Branch, Houston, TX` | `/spring-branch-houston-tx/` |

Detection logic in `ZillowScraper._build_search_url(query)`:
- All digits → zip code → `/{metro-slug}/{zip}/`
- Contains comma with city + state → slugify as neighborhood or metro
- Fallback to current behavior

## Watchlist

A "Saved Areas" feature in the dashboard for recurring searches.

### Storage

Database table `WatchlistRow`:
- `id` (PK), `query` (search string), `label` (optional display name), `created_at`

### Dashboard UI

- "Save" button next to search bar saves current query
- Saved areas rendered as clickable chips below the search input
- Click a chip to run that search
- "X" to remove a saved area
- "Scan All" button scans all saved areas and merges results

### API Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/watchlist` | GET | List saved areas |
| `/api/watchlist` | POST | Add an area |
| `/api/watchlist/{id}` | DELETE | Remove an area |
| `/api/scan` | GET | Updated to accept `query` param (zip, neighborhood, or metro) |

### Scheduler Integration

When the watchlist is non-empty, the periodic scan uses watchlist entries instead of configured markets.

## Error Handling

- **Bad input (404 / empty results):** Toast message: "No listings found for 'X'. Check the zip code or neighborhood name."
- **Duplicate watchlist entries:** Case-insensitive rejection, highlight existing chip.
- **Ambiguous neighborhoods:** Hint users to use "Neighborhood, City, ST" format.
- **Merged result deduplication:** Deduplicate by `zpid` when scanning multiple areas.

## Out of Scope

- No map view
- No geocoding service (rely on Zillow URL routing)
- No CLI changes (dashboard only)
- No changes to analysis, alerts, or comps pipelines
- No pagination (Zillow's ~40 results per page is sufficient for now)
