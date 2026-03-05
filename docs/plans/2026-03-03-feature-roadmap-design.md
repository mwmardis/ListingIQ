# ListingIQ Feature Roadmap Design

**Date:** 2026-03-03
**Approach:** Fix-the-Foundation First (3 tiers based on dependency)

## Tier 1 — Fix What's Broken

### 1.1 Rebalance Deal Scanner

**Problem:** Flip ARV fallback (`price / 0.65`) makes most properties look like viable flips. BRRR and cash flow depend on rent estimates that are often too conservative. Result: scanner returns mostly flip deals.

**Fixes:**

**A. Conservative ARV fallback for flips:**
- Replace `arv = price / 0.65` with age-aware fallback:
  - Under 15 years old: `price * 1.15`
  - 15-30 years: `price * 1.25`
  - 30+ years: `price * 1.35`

**B. Rent estimation tuning:**
- Ensure comp-based estimate is always preferred over formula
- For multi-family: estimate rent per unit, not per whole property

**C. Score rebalancing:**
- Cash flow: add cash-flow-per-dollar-invested component (cheap properties currently penalized)
- BRRR: add deal safety margin component (how far above minimums)

**D. Threshold adjustments:**
- Lower cash flow `min_cap_rate` default from 6% to 5%
- All thresholds remain configurable via TOML

### 1.2 Data Model Expansion

Add to `Listing` model:
```python
units: int = 1                      # 1 for SFH, 2-4 for small multi
has_pool: bool | None = None        # None = unknown
stories: int = 0
school_rating: float | None = None  # 1-10 if available
flood_zone: str | None = None
crime_score: float | None = None
```

New model:
```python
class UnitMix(BaseModel):
    unit_number: int
    beds: int = 0
    baths: float = 0
    sqft: int = 0
    estimated_rent: float = 0.0
```

Scraper changes: extract pool, school rating, flood zone, crime, stories, unit count from Zillow API responses where available. Fields default to `None` when data unavailable.

### 1.3 Small Multi-Family Analysis (2-4 Units)

When `listing.units > 1`:
- Estimate rent per unit (total sqft / units, apply per-sqft rate)
- Cash flow uses aggregate rental income vs single mortgage
- BRRR uses aggregate rent for CoC calculation
- Flip is unaffected (no rental dependency)

Example: 2,400 sqft duplex = two 1,200 sqft units at ~$1,320/mo each = $2,640 total rent.

## Tier 2 — New Analysis Capabilities

### 2.1 Days on Market — Display + Offer Impact

**Display:**
- Show DOM prominently on deal cards, color-coded:
  - Green: <30 DOM
  - Yellow: 30-90 DOM
  - Red: 90+ DOM
- "New listing" badge for DOM < 7

**Offer price adjustment:**
- DOM 0-30: no adjustment
- DOM 31-60: suggest 2% additional discount
- DOM 61-90: suggest 5% additional discount
- DOM 90+: suggest 8% additional discount
- Show both base offer and DOM-adjusted offer

Config:
```toml
[analysis.offer]
dom_discount_30_60 = 0.02
dom_discount_60_90 = 0.05
dom_discount_90_plus = 0.08
```

### 2.2 Room Addition Potential

Sqft-per-bedroom ratio analysis for BRRR and flip deals:
- `> 600 sqft/bed` = "Likely room addition potential"
- `> 800 sqft/bed` = "Strong room addition potential"

Display: metric + flag on deal cards. Also calculate potential ARV increase from adding a bedroom based on comp spread.

### 2.3 Offer Calculator — Mortgage Points Slider + Table

**Slider:** 0 to 3 points in 0.25 increments. Each point = 0.25% rate reduction.

**Comparison table:**
| Points | Rate | Monthly Payment | Total Interest | Break-even Month | Point Cost |
|--------|------|----------------|---------------|-----------------|------------|
| 0-3 | dynamic | dynamic | dynamic | dynamic | dynamic |

Break-even = point cost / monthly savings.

### 2.4 Offer Calculator — Cash-on-Cash Return Display

Show CoC return at the calculated offer price for BRRR and cash flow strategies. Already computed by analyzers; surface it in offer results.

### 2.5 Secondary Data Display (Informational Only)

Collapsible "Property Details" panel on deal cards:

| Data | Source | Display |
|------|--------|---------|
| School ratings | Scraper data | "Schools: 7/10" |
| Property taxes | `tax_annual` (existing) | "$4,200/yr" |
| Home age | `year_built` (existing) | "Built 1985 (41 years)" |
| Pool | Scraper data | "Pool: Yes/No" |
| Flood zone | Scraper data | "Flood Zone: X" or "Unknown" |
| Crime rates | Scraper data | "Crime: Low/Medium/High" or "Unknown" |
| Lot size | `lot_sqft` (existing) | "Lot: 0.25 acres" |

No filtering or score impact — display only.

## Tier 3 — Automation

### 3.1 Instant Alerts (Score >= 90)

- Configure `min_deal_score = 90` for instant alerts
- Immediate email when a scan finds a 90+ deal
- Uses existing email channel infrastructure

### 3.2 Scheduled Email Digests

Config:
```toml
[alerts.digest]
enabled = true
schedule = "daily"      # "daily" or "weekly"
time = "08:00"          # Local time
min_score = 70          # Include deals above this score
```

- APScheduler job queries DB for deals since last digest
- Groups by strategy, sorts by score
- Single HTML email with summary stats + deal cards

**Two alert tiers:**
1. Instant (score >= 90): hot deal email sent immediately
2. Digest (score >= 70): included in daily/weekly summary

## Architecture Notes

- All new fields on `Listing` are optional with sensible defaults — no breaking changes
- Scraper enhancements are best-effort; missing data displays as "Unknown"
- Offer calculator DOM adjustment is additive to existing strategy-based calculation
- Multi-family analysis is a conditional path in existing analyzers, not a new strategy
- Room addition potential is a computed display metric, not a stored field
- Digest system reuses existing email channel; just adds a scheduled aggregation job
