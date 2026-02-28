# ListingIQ

MLS deal alert system for real estate investors. Scrapes property listings from multiple sources, analyzes them for investment potential (BRRR, cash flow, flip), and alerts you when good deals appear.

## Features

- **Multi-source scraping** — Redfin, Zillow, Realtor.com
- **Three analysis strategies:**
  - **BRRR** (Buy, Rehab, Rent, Refinance, Repeat) — scores based on cash-on-cash return, equity capture, and cash left in deal
  - **Cash Flow** — evaluates cap rate, DSCR, monthly cash flow, GRM
  - **Flip** — estimates profit, ROI, and profit per month
- **Configurable parameters** — every threshold, rate, and assumption is tunable via TOML config
- **Multiple alert channels** — console, email (SMTP), SMS (Twilio), webhooks (Slack/Discord)
- **Scheduled scanning** — set it and forget it with configurable intervals
- **Web dashboard** — browser-based UI for scanning and analyzing deals
- **CLI** — full command-line interface for scanning, analyzing, and watching
- **SQLite storage** — tracks listings, price history, and deal scores over time

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Analyze a specific property
listingiq analyze "123 Main St" --price 200000 --sqft 1500 --beds 3 --baths 2

# Scan a market for deals
listingiq scan --market "Austin, TX" --source redfin

# Start the web dashboard
listingiq serve

# Run the scheduled watcher
listingiq watch
```

## Configuration

Copy the default config and customize:

```bash
cp config/default.toml config/local.toml
```

Key settings in `config/local.toml`:

```toml
[scraper.search]
markets = ["Austin, TX", "San Antonio, TX"]
min_price = 100000
max_price = 400000

[analysis.cash_flow]
down_payment_pct = 0.25
interest_rate = 0.065
min_monthly_cash_flow = 250

[analysis.brrr]
min_cash_on_cash_return = 10.0

[alerts]
channels = ["console", "email"]
min_deal_score = 75
```

See `config/default.toml` for all available parameters.

## CLI Commands

| Command | Description |
|---------|-------------|
| `listingiq scan` | Scrape listings and analyze for deals |
| `listingiq analyze` | Analyze a single property by address/price |
| `listingiq watch` | Start scheduled scanning |
| `listingiq serve` | Launch web dashboard |
| `listingiq config-show` | Display current configuration |

### Scan Options

```
--market, -m    Target market (e.g., "Austin, TX")
--source, -s    Scraper source (redfin, zillow, realtor)
--strategy      Only run specific strategy (brrr, cash_flow, flip)
--min-score     Minimum deal score to display (0-100)
--limit, -l     Max number of deals to show
--no-alert      Skip sending alerts
--config, -c    Path to custom config file
```

## Deal Scoring

Each strategy scores deals on a 0–100 scale:

**BRRR** weights: Cash-on-cash return (40pts), investment recovery (25pts), monthly cash flow (20pts), equity captured (15pts)

**Cash Flow** weights: Monthly cash flow (35pts), cap rate (25pts), cash-on-cash return (20pts), DSCR (10pts), GRM (10pts)

**Flip** weights: Estimated profit (40pts), ROI (30pts), profit/month (20pts), ARV spread (10pts)

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```
