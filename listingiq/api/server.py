"""FastAPI web dashboard for ListingIQ."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from listingiq.config import AppConfig
from listingiq.models import Listing
from listingiq.analysis.engine import DealAnalyzer
from listingiq.analysis.offer import OfferCalculator
from listingiq.comps.rental import RentalCompService
from listingiq.comps.sales import SalesCompService
from listingiq.scrapers import get_scraper
from listingiq.db.repository import Repository


def create_app(cfg: AppConfig) -> FastAPI:
    app = FastAPI(title="ListingIQ", version="0.2.0")
    repo = Repository(cfg.database.url)
    analyzer = DealAnalyzer(cfg.analysis)
    offer_calc = OfferCalculator(cfg.analysis)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Serve a simple dashboard page."""
        return _dashboard_html()

    @app.get("/api/scan")
    async def scan(
        market: str = Query(None),
        source: str = Query(None),
        min_score: int = Query(70),
        limit: int = Query(20),
    ):
        """Trigger a scan and return results."""
        scraper_cfg = cfg.scraper.model_copy(deep=True)
        if market:
            scraper_cfg.search.markets = [market]

        sources = [source] if source else cfg.scraper.sources
        all_listings: list[Listing] = []

        for source_name in sources:
            try:
                scraper_cls = get_scraper(source_name)
                scraper = scraper_cls(scraper_cfg)
                listings = await scraper.scrape()
                all_listings.extend(listings)
                await scraper.close()
            except Exception as e:
                return {"error": f"Scraper {source_name} failed: {str(e)}"}

        deals = analyzer.get_top_deals(all_listings, min_score=min_score, limit=limit)

        return {
            "total_listings": len(all_listings),
            "qualifying_deals": len(deals),
            "deals": [
                {
                    "score": d.score,
                    "strategy": d.strategy.value,
                    "address": d.listing.full_address,
                    "price": d.listing.price,
                    "beds": d.listing.beds,
                    "baths": d.listing.baths,
                    "sqft": d.listing.sqft,
                    "url": d.listing.url,
                    "metrics": d.metrics,
                    "summary": d.summary,
                }
                for d in deals
            ],
        }

    @app.get("/api/analyze")
    async def analyze_property(
        price: float = Query(...),
        sqft: int = Query(1500),
        beds: int = Query(3),
        baths: float = Query(2),
        tax: float = Query(0),
        hoa: float = Query(0),
        address: str = Query("Manual Entry"),
        city: str = Query(""),
        state: str = Query(""),
    ):
        """Analyze a single property, with optional comp-based estimates."""
        listing = Listing(
            source="api",
            source_id="api-entry",
            address=address,
            city=city,
            state=state,
            zip_code="",
            price=price,
            beds=beds,
            baths=baths,
            sqft=sqft,
            tax_annual=tax,
            hoa_monthly=hoa,
        )

        rent_estimate = None
        arv_estimate = None
        comp_info: dict = {}

        # Fetch comps if enabled and location is provided
        if cfg.analysis.comps.enabled and city:
            rental_svc = RentalCompService(cfg.analysis.comps, cfg.scraper)
            sales_svc = SalesCompService(cfg.analysis.comps)
            try:
                rent, rental_comps, rent_conf = await rental_svc.estimate_rent(listing)
                rent_estimate = rent
                comp_info["rent_estimate"] = rent
                comp_info["rent_confidence"] = rent_conf
                comp_info["rental_comps_count"] = len(rental_comps)
            except Exception:
                pass
            finally:
                await rental_svc.close()

            try:
                arv, sales_comps, arv_conf = await sales_svc.estimate_arv(listing)
                arv_estimate = arv
                comp_info["arv_estimate"] = arv
                comp_info["arv_confidence"] = arv_conf
                comp_info["sales_comps_count"] = len(sales_comps)
            except Exception:
                pass
            finally:
                await sales_svc.close()

        deals = analyzer.analyze_listing(
            listing, rent_estimate=rent_estimate, arv_estimate=arv_estimate
        )
        return {
            "comps": comp_info,
            "analyses": [
                {
                    "strategy": d.strategy.value,
                    "score": d.score,
                    "meets_criteria": d.meets_criteria,
                    "metrics": d.metrics,
                    "summary": d.summary,
                }
                for d in deals
            ],
        }

    @app.get("/api/offer-price")
    async def offer_price(
        price: float = Query(..., description="Current list price"),
        sqft: int = Query(1500),
        beds: int = Query(3),
        baths: float = Query(2),
        tax: float = Query(0),
        hoa: float = Query(0),
        address: str = Query("Manual Entry"),
        city: str = Query(""),
        state: str = Query(""),
        strategy: str = Query(None, description="Strategy to calculate for (default: all)"),
        target_metric: str = Query(None, description="Metric to optimize"),
        target_value: float = Query(None, description="Target value for the metric"),
    ):
        """Calculate max offer price to achieve a target return."""
        listing = Listing(
            source="api",
            source_id="api-entry",
            address=address,
            city=city,
            state=state,
            zip_code="",
            price=price,
            beds=beds,
            baths=baths,
            sqft=sqft,
            tax_annual=tax,
            hoa_monthly=hoa,
        )

        rent_estimate = None
        arv_estimate = None

        if cfg.analysis.comps.enabled and city:
            rental_svc = RentalCompService(cfg.analysis.comps, cfg.scraper)
            sales_svc = SalesCompService(cfg.analysis.comps)
            try:
                rent, _, _ = await rental_svc.estimate_rent(listing)
                rent_estimate = rent
            except Exception:
                pass
            finally:
                await rental_svc.close()

            try:
                arv, _, _ = await sales_svc.estimate_arv(listing)
                arv_estimate = arv
            except Exception:
                pass
            finally:
                await sales_svc.close()

        if strategy:
            results = [offer_calc.calculate_offer_price(
                listing,
                strategy=strategy,
                target_metric=target_metric,
                target_value=target_value,
                rent_estimate=rent_estimate,
                arv_estimate=arv_estimate,
            )]
        else:
            results = offer_calc.calculate_all_offers(
                listing,
                rent_estimate=rent_estimate,
                arv_estimate=arv_estimate,
            )

        return {
            "list_price": price,
            "offers": [
                {
                    "strategy": r.strategy.value,
                    "target_metric": r.target_metric,
                    "target_value": r.target_value,
                    "max_offer_price": r.max_offer_price,
                    "discount_from_list": r.discount_from_list,
                    "metrics_at_offer": r.metrics_at_offer,
                }
                for r in results
            ],
        }

    @app.get("/api/deals")
    async def get_deals(
        strategy: str = Query(None),
        limit: int = Query(20),
    ):
        """Get stored deals from the database."""
        deals = repo.get_top_deals(limit=limit, strategy=strategy)
        return {
            "deals": [
                {
                    "id": d.id,
                    "listing_id": d.listing_id,
                    "strategy": d.strategy,
                    "score": d.score,
                    "metrics": d.metrics,
                    "meets_criteria": d.meets_criteria,
                    "summary": d.summary,
                    "analyzed_at": d.analyzed_at.isoformat() if d.analyzed_at else None,
                }
                for d in deals
            ]
        }

    @app.get("/api/config")
    async def get_config():
        """Return current configuration."""
        return cfg.model_dump()

    return app


def _dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ListingIQ Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0f172a; color: #e2e8f0; padding: 2rem; }
        h1 { color: #38bdf8; margin-bottom: 0.5rem; font-size: 2rem; }
        .subtitle { color: #94a3b8; margin-bottom: 2rem; }
        .controls { display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }
        input, select, button { padding: 0.6rem 1rem; border-radius: 8px; border: 1px solid #334155;
               background: #1e293b; color: #e2e8f0; font-size: 0.9rem; }
        button { background: #2563eb; border-color: #2563eb; cursor: pointer; font-weight: 600; }
        button:hover { background: #1d4ed8; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                 gap: 1rem; margin-bottom: 2rem; }
        .stat-card { background: #1e293b; border-radius: 12px; padding: 1.5rem;
                     border: 1px solid #334155; }
        .stat-card .label { color: #94a3b8; font-size: 0.85rem; }
        .stat-card .value { font-size: 1.8rem; font-weight: 700; color: #38bdf8; }
        .deals { display: grid; gap: 1rem; }
        .deal-card { background: #1e293b; border-radius: 12px; padding: 1.5rem;
                     border: 1px solid #334155; transition: border-color 0.2s; }
        .deal-card:hover { border-color: #38bdf8; }
        .deal-header { display: flex; justify-content: space-between; align-items: center;
                       margin-bottom: 1rem; }
        .deal-score { font-size: 1.4rem; font-weight: 700; }
        .score-high { color: #22c55e; }
        .score-mid { color: #eab308; }
        .score-low { color: #f87171; }
        .deal-strategy { background: #334155; padding: 0.25rem 0.75rem; border-radius: 9999px;
                         font-size: 0.8rem; text-transform: uppercase; font-weight: 600; }
        .deal-address { font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem; }
        .deal-meta { display: flex; gap: 1.5rem; color: #94a3b8; font-size: 0.9rem;
                     margin-bottom: 1rem; }
        .deal-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                        gap: 0.5rem; }
        .metric { background: #0f172a; padding: 0.5rem 0.75rem; border-radius: 6px; }
        .metric .label { font-size: 0.75rem; color: #64748b; }
        .metric .value { font-weight: 600; }
        a { color: #38bdf8; text-decoration: none; }
        a:hover { text-decoration: underline; }
        #loading { text-align: center; padding: 3rem; color: #64748b; }
        .analyze-section { background: #1e293b; border-radius: 12px; padding: 1.5rem;
                           border: 1px solid #334155; margin-bottom: 2rem; }
        .analyze-section h2 { margin-bottom: 1rem; color: #38bdf8; }
        .form-row { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem; }
        .form-group { display: flex; flex-direction: column; gap: 0.25rem; }
        .form-group label { font-size: 0.8rem; color: #94a3b8; }
    </style>
</head>
<body>
    <h1>ListingIQ</h1>
    <p class="subtitle">Real Estate Deal Analyzer & Alert System</p>

    <div class="analyze-section">
        <h2>Quick Analysis</h2>
        <div class="form-row">
            <div class="form-group">
                <label>Price ($)</label>
                <input type="number" id="a-price" placeholder="250000" value="250000">
            </div>
            <div class="form-group">
                <label>Sqft</label>
                <input type="number" id="a-sqft" placeholder="1500" value="1500">
            </div>
            <div class="form-group">
                <label>Beds</label>
                <input type="number" id="a-beds" placeholder="3" value="3">
            </div>
            <div class="form-group">
                <label>Baths</label>
                <input type="number" id="a-baths" placeholder="2" value="2">
            </div>
            <div class="form-group">
                <label>Annual Tax</label>
                <input type="number" id="a-tax" placeholder="3000" value="3000">
            </div>
            <div class="form-group">
                <label>&nbsp;</label>
                <button onclick="analyzeProperty()">Analyze</button>
            </div>
        </div>
        <div id="analysis-results"></div>
    </div>

    <div class="controls">
        <input type="text" id="market" placeholder="Market (e.g. Austin, TX)" value="Austin, TX">
        <select id="source">
            <option value="redfin">Redfin</option>
            <option value="zillow">Zillow</option>
            <option value="realtor">Realtor.com</option>
        </select>
        <input type="number" id="min-score" placeholder="Min Score" value="50" min="0" max="100">
        <button onclick="runScan()">Scan for Deals</button>
    </div>

    <div class="stats" id="stats" style="display:none;">
        <div class="stat-card">
            <div class="label">Listings Found</div>
            <div class="value" id="stat-listings">0</div>
        </div>
        <div class="stat-card">
            <div class="label">Qualifying Deals</div>
            <div class="value" id="stat-deals">0</div>
        </div>
        <div class="stat-card">
            <div class="label">Best Score</div>
            <div class="value" id="stat-best">-</div>
        </div>
    </div>

    <div id="loading" style="display:none;">Scanning listings...</div>
    <div class="deals" id="deals"></div>

    <script>
        async function runScan() {
            const market = document.getElementById('market').value;
            const source = document.getElementById('source').value;
            const minScore = document.getElementById('min-score').value;

            document.getElementById('loading').style.display = 'block';
            document.getElementById('deals').innerHTML = '';
            document.getElementById('stats').style.display = 'none';

            try {
                const resp = await fetch(
                    `/api/scan?market=${encodeURIComponent(market)}&source=${source}&min_score=${minScore}`
                );
                const data = await resp.json();

                if (data.error) {
                    document.getElementById('deals').innerHTML =
                        `<div class="deal-card"><p style="color:#f87171">${data.error}</p></div>`;
                    return;
                }

                document.getElementById('stat-listings').textContent = data.total_listings;
                document.getElementById('stat-deals').textContent = data.qualifying_deals;
                document.getElementById('stat-best').textContent =
                    data.deals.length ? data.deals[0].score : '-';
                document.getElementById('stats').style.display = 'grid';

                renderDeals(data.deals);
            } catch (e) {
                document.getElementById('deals').innerHTML =
                    `<div class="deal-card"><p style="color:#f87171">Error: ${e.message}</p></div>`;
            } finally {
                document.getElementById('loading').style.display = 'none';
            }
        }

        function renderDeals(deals) {
            const container = document.getElementById('deals');
            if (!deals.length) {
                container.innerHTML = '<div class="deal-card"><p>No deals found matching criteria.</p></div>';
                return;
            }

            container.innerHTML = deals.map(deal => {
                const scoreClass = deal.score >= 80 ? 'score-high' :
                                   deal.score >= 60 ? 'score-mid' : 'score-low';
                const metrics = deal.metrics;
                const metricHtml = Object.entries(metrics).map(([k, v]) => {
                    const label = k.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
                    let val = typeof v === 'number' ?
                        (k.includes('pct') || k.includes('rate') || k.includes('return') || k === 'roi' || k === 'dscr'
                            ? v.toFixed(1) + (k === 'dscr' ? 'x' : '%')
                            : '$' + v.toLocaleString('en-US', {maximumFractionDigits: 0}))
                        : v;
                    return `<div class="metric"><div class="label">${label}</div><div class="value">${val}</div></div>`;
                }).join('');

                return `
                    <div class="deal-card">
                        <div class="deal-header">
                            <span class="deal-score ${scoreClass}">${deal.score}</span>
                            <span class="deal-strategy">${deal.strategy.replace('_', ' ')}</span>
                        </div>
                        <div class="deal-address">
                            ${deal.url ? `<a href="${deal.url}" target="_blank">${deal.address}</a>` : deal.address}
                        </div>
                        <div class="deal-meta">
                            <span>$${deal.price.toLocaleString()}</span>
                            <span>${deal.beds}bd / ${deal.baths}ba</span>
                            <span>${deal.sqft ? deal.sqft.toLocaleString() + ' sqft' : 'N/A'}</span>
                        </div>
                        <div class="deal-metrics">${metricHtml}</div>
                    </div>`;
            }).join('');
        }

        async function analyzeProperty() {
            const price = document.getElementById('a-price').value;
            const sqft = document.getElementById('a-sqft').value;
            const beds = document.getElementById('a-beds').value;
            const baths = document.getElementById('a-baths').value;
            const tax = document.getElementById('a-tax').value;

            const resp = await fetch(
                `/api/analyze?price=${price}&sqft=${sqft}&beds=${beds}&baths=${baths}&tax=${tax}`
            );
            const data = await resp.json();

            const container = document.getElementById('analysis-results');
            container.innerHTML = data.analyses.map(a => {
                const scoreClass = a.score >= 80 ? 'score-high' :
                                   a.score >= 60 ? 'score-mid' : 'score-low';
                return `
                    <div class="deal-card" style="margin-top:1rem">
                        <div class="deal-header">
                            <span class="deal-score ${scoreClass}">${a.score}</span>
                            <span class="deal-strategy">${a.strategy.replace('_', ' ')}</span>
                        </div>
                        <pre style="white-space:pre-wrap;color:#94a3b8;font-size:0.85rem">${a.summary}</pre>
                    </div>`;
            }).join('');
        }
    </script>
</body>
</html>"""
