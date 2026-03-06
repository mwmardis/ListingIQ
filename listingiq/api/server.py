"""FastAPI web dashboard for ListingIQ."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from listingiq.config import AppConfig, load_config
from listingiq.models import Listing
from listingiq.analysis.engine import DealAnalyzer
from listingiq.analysis.offer import OfferCalculator
from listingiq.analysis.room_potential import assess_room_potential
from listingiq.analysis.points import calculate_points_table
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
                    "room_potential": assess_room_potential(d.listing),
                    "days_on_market": d.listing.days_on_market,
                    "secondary": {
                        "year_built": d.listing.year_built,
                        "tax_annual": d.listing.tax_annual,
                        "lot_sqft": d.listing.lot_sqft,
                        "has_pool": d.listing.has_pool,
                        "school_rating": d.listing.school_rating,
                        "flood_zone": d.listing.flood_zone,
                        "crime_score": d.listing.crime_score,
                        "stories": d.listing.stories,
                    },
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
        rent: float = Query(None, description="Manual monthly rent estimate"),
        arv: float = Query(None, description="Manual ARV estimate"),
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

        # Use user-provided values; comp lookup provides comparison data
        rent_estimate = rent
        arv_estimate = arv
        comp_info: dict = {}

        # Fetch comps if enabled and location is provided (for comparison)
        if cfg.analysis.comps.enabled and city:
            rental_svc = RentalCompService(cfg.analysis.comps, cfg.scraper)
            sales_svc = SalesCompService(cfg.analysis.comps)
            try:
                comp_rent, rental_comps, rent_conf = await rental_svc.estimate_rent(listing)
                comp_info["rent_estimate"] = comp_rent
                comp_info["rent_confidence"] = rent_conf
                comp_info["rental_comps_count"] = len(rental_comps)
                if rent_estimate is None:
                    rent_estimate = comp_rent
            except Exception:
                pass
            finally:
                await rental_svc.close()

            try:
                comp_arv, sales_comps, arv_conf = await sales_svc.estimate_arv(listing)
                comp_info["arv_estimate"] = comp_arv
                comp_info["arv_confidence"] = arv_conf
                comp_info["sales_comps_count"] = len(sales_comps)
                if arv_estimate is None:
                    arv_estimate = comp_arv
            except Exception:
                pass
            finally:
                await sales_svc.close()

        if rent_estimate is not None:
            comp_info["rent_used"] = rent_estimate
        if arv_estimate is not None:
            comp_info["arv_used"] = arv_estimate

        deals = analyzer.analyze_listing(
            listing, rent_estimate=rent_estimate, arv_estimate=arv_estimate
        )
        return {
            "comps": comp_info,
            "room_potential": assess_room_potential(listing),
            "days_on_market": listing.days_on_market,
            "secondary": {
                "year_built": listing.year_built,
                "tax_annual": listing.tax_annual,
                "lot_sqft": listing.lot_sqft,
                "has_pool": listing.has_pool,
                "school_rating": listing.school_rating,
                "flood_zone": listing.flood_zone,
                "crime_score": listing.crime_score,
                "stories": listing.stories,
            },
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
        rent: float = Query(None, description="Manual monthly rent estimate"),
        arv: float = Query(None, description="Manual ARV estimate"),
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

        rent_estimate = rent
        arv_estimate = arv

        if cfg.analysis.comps.enabled and city:
            rental_svc = RentalCompService(cfg.analysis.comps, cfg.scraper)
            sales_svc = SalesCompService(cfg.analysis.comps)
            try:
                comp_rent, _, _ = await rental_svc.estimate_rent(listing)
                if rent_estimate is None:
                    rent_estimate = comp_rent
            except Exception:
                pass
            finally:
                await rental_svc.close()

            try:
                comp_arv, _, _ = await sales_svc.estimate_arv(listing)
                if arv_estimate is None:
                    arv_estimate = comp_arv
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

        offer_dicts = []
        for r in results:
            points_data = calculate_points_table(
                loan_amount=r.max_offer_price * (1 - cfg.analysis.cash_flow.down_payment_pct),
                base_rate=cfg.analysis.cash_flow.interest_rate,
            )
            offer_dicts.append({
                "strategy": r.strategy.value,
                "target_metric": r.target_metric,
                "target_value": r.target_value,
                "max_offer_price": r.max_offer_price,
                "dom_adjusted_price": r.dom_adjusted_price,
                "discount_from_list": r.discount_from_list,
                "metrics_at_offer": r.metrics_at_offer,
                "points_table": points_data,
            })

        return {
            "list_price": price,
            "offers": offer_dicts,
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
    <title>ListingIQ</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=Playfair+Display:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-root: #08090d;
            --bg-surface: #101218;
            --bg-card: rgba(18, 20, 28, 0.7);
            --bg-card-hover: rgba(24, 27, 38, 0.85);
            --bg-input: rgba(14, 16, 22, 0.8);
            --border: rgba(255, 255, 255, 0.06);
            --border-hover: rgba(255, 255, 255, 0.12);
            --text-primary: #eef0f6;
            --text-secondary: #7a7f96;
            --text-muted: #4a4f64;
            --accent: #34d399;
            --accent-dim: rgba(52, 211, 153, 0.12);
            --accent-glow: rgba(52, 211, 153, 0.25);
            --gold: #f5c842;
            --gold-dim: rgba(245, 200, 66, 0.1);
            --red: #f87171;
            --red-dim: rgba(248, 113, 113, 0.1);
            --blue: #60a5fa;
            --blue-dim: rgba(96, 165, 250, 0.1);
            --radius: 16px;
            --radius-sm: 10px;
            --radius-xs: 6px;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'DM Sans', sans-serif;
            background: var(--bg-root);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* ── Grain Texture Overlay ── */
        body::before {
            content: '';
            position: fixed;
            inset: 0;
            z-index: 9999;
            pointer-events: none;
            opacity: 0.025;
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
            background-repeat: repeat;
            background-size: 128px 128px;
        }

        /* ── Ambient Glow ── */
        body::after {
            content: '';
            position: fixed;
            top: -30%;
            left: -10%;
            width: 70%;
            height: 70%;
            background: radial-gradient(ellipse, rgba(52, 211, 153, 0.04) 0%, transparent 70%);
            pointer-events: none;
            z-index: 0;
        }

        /* ── Layout Shell ── */
        .app-layout {
            display: grid;
            grid-template-columns: 260px 1fr;
            min-height: 100vh;
            position: relative;
            z-index: 1;
        }

        /* ── Sidebar ── */
        .sidebar {
            background: var(--bg-surface);
            border-right: 1px solid var(--border);
            padding: 2rem 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 2rem;
            position: sticky;
            top: 0;
            height: 100vh;
            overflow-y: auto;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .logo-icon {
            width: 38px;
            height: 38px;
            background: linear-gradient(135deg, var(--accent), #059669);
            border-radius: var(--radius-sm);
            display: grid;
            place-items: center;
            font-weight: 700;
            font-size: 0.9rem;
            color: #08090d;
            letter-spacing: -0.5px;
            box-shadow: 0 0 20px var(--accent-glow);
        }

        .logo-text {
            font-family: 'Playfair Display', serif;
            font-size: 1.35rem;
            font-weight: 600;
            letter-spacing: -0.3px;
        }

        .logo-text span {
            color: var(--accent);
        }

        .nav {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }

        .nav-label {
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--text-muted);
            padding: 0 0.75rem;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.65rem 0.75rem;
            border-radius: var(--radius-sm);
            color: var(--text-secondary);
            font-size: 0.88rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            border: 1px solid transparent;
        }

        .nav-item:hover {
            color: var(--text-primary);
            background: rgba(255, 255, 255, 0.03);
        }

        .nav-item.active {
            color: var(--accent);
            background: var(--accent-dim);
            border-color: rgba(52, 211, 153, 0.15);
        }

        .nav-icon {
            width: 18px;
            height: 18px;
            opacity: 0.7;
            flex-shrink: 0;
        }

        .nav-item.active .nav-icon { opacity: 1; }

        .sidebar-footer {
            margin-top: auto;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
        }

        .version-badge {
            font-size: 0.72rem;
            color: var(--text-muted);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .version-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--accent);
            box-shadow: 0 0 6px var(--accent-glow);
            animation: pulse 2s ease infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* ── Main Content ── */
        .main {
            padding: 2.5rem 3rem;
            max-width: 1200px;
        }

        /* ── Page Sections ── */
        .page-section {
            display: none;
            animation: fadeUp 0.4s ease;
        }

        .page-section.active {
            display: block;
        }

        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* ── Page Header ── */
        .page-header {
            margin-bottom: 2.5rem;
        }

        .page-header h1 {
            font-family: 'Playfair Display', serif;
            font-size: 2rem;
            font-weight: 600;
            letter-spacing: -0.5px;
            margin-bottom: 0.35rem;
        }

        .page-header p {
            color: var(--text-secondary);
            font-size: 0.92rem;
        }

        /* ── Glass Card ── */
        .glass-card {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.75rem;
            transition: all 0.3s ease;
        }

        .glass-card:hover {
            border-color: var(--border-hover);
            background: var(--bg-card-hover);
        }

        /* ── Stat Cards ── */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            position: relative;
            overflow: hidden;
        }

        .stat-card::after {
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            width: 80px;
            height: 80px;
            border-radius: 50%;
            filter: blur(40px);
            opacity: 0.15;
            pointer-events: none;
        }

        .stat-card:nth-child(1)::after { background: var(--accent); }
        .stat-card:nth-child(2)::after { background: var(--gold); }
        .stat-card:nth-child(3)::after { background: var(--blue); }

        .stat-label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            font-weight: 600;
            margin-bottom: 0.75rem;
        }

        .stat-value {
            font-family: 'Playfair Display', serif;
            font-size: 2.2rem;
            font-weight: 600;
            line-height: 1;
        }

        .stat-card:nth-child(1) .stat-value { color: var(--accent); }
        .stat-card:nth-child(2) .stat-value { color: var(--gold); }
        .stat-card:nth-child(3) .stat-value { color: var(--blue); }

        /* ── Form Controls ── */
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1rem;
            margin-bottom: 1.25rem;
        }

        .field {
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
        }

        .field label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            font-weight: 600;
        }

        input, select {
            background: var(--bg-input);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 0.7rem 1rem;
            color: var(--text-primary);
            font-family: 'DM Sans', sans-serif;
            font-size: 0.88rem;
            transition: all 0.2s ease;
            outline: none;
        }

        input:focus, select:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-dim);
        }

        input::placeholder {
            color: var(--text-muted);
        }

        select {
            cursor: pointer;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%234a4f64'%3E%3Cpath d='M6 8.5L1 3.5h10z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 12px center;
            padding-right: 2rem;
        }

        select option {
            background: var(--bg-surface);
            color: var(--text-primary);
        }

        /* ── Buttons ── */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.7rem 1.5rem;
            border-radius: var(--radius-sm);
            font-family: 'DM Sans', sans-serif;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s ease;
            border: none;
            outline: none;
            position: relative;
            overflow: hidden;
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent), #059669);
            color: #08090d;
            box-shadow: 0 2px 12px var(--accent-dim);
        }

        .btn-primary:hover {
            box-shadow: 0 4px 24px var(--accent-glow);
            transform: translateY(-1px);
        }

        .btn-primary:active {
            transform: translateY(0);
        }

        .btn-ghost {
            background: transparent;
            color: var(--text-secondary);
            border: 1px solid var(--border);
        }

        .btn-ghost:hover {
            color: var(--text-primary);
            border-color: var(--border-hover);
            background: rgba(255, 255, 255, 0.03);
        }

        .btn-row {
            display: flex;
            gap: 0.75rem;
            align-items: center;
        }

        /* ── Section Headers ── */
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }

        .section-title {
            font-family: 'Playfair Display', serif;
            font-size: 1.15rem;
            font-weight: 600;
        }

        /* ── Score Ring (SVG) ── */
        .score-ring {
            width: 56px;
            height: 56px;
            flex-shrink: 0;
        }

        .score-ring-bg {
            fill: none;
            stroke: rgba(255, 255, 255, 0.05);
            stroke-width: 4;
        }

        .score-ring-fill {
            fill: none;
            stroke-width: 4;
            stroke-linecap: round;
            transition: stroke-dashoffset 0.8s ease;
            transform: rotate(-90deg);
            transform-origin: 50% 50%;
        }

        .score-ring-text {
            font-family: 'DM Sans', sans-serif;
            font-weight: 700;
            font-size: 13px;
            fill: var(--text-primary);
            text-anchor: middle;
            dominant-baseline: central;
        }

        /* ── Deal Cards ── */
        .deals-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .deal-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            transition: all 0.3s ease;
            animation: fadeUp 0.4s ease backwards;
        }

        .deal-card:hover {
            border-color: var(--border-hover);
            background: var(--bg-card-hover);
            transform: translateY(-2px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }

        .deal-top {
            display: flex;
            align-items: center;
            gap: 1.25rem;
            margin-bottom: 1rem;
        }

        .deal-info { flex: 1; }

        .deal-address {
            font-weight: 600;
            font-size: 1rem;
            margin-bottom: 0.3rem;
        }

        .deal-address a {
            color: var(--text-primary);
            text-decoration: none;
            transition: color 0.2s;
        }

        .deal-address a:hover { color: var(--accent); }

        .deal-meta {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 0.82rem;
            color: var(--text-secondary);
        }

        .deal-meta-sep {
            width: 3px;
            height: 3px;
            border-radius: 50%;
            background: var(--text-muted);
        }

        .strategy-tag {
            padding: 0.2rem 0.65rem;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
        }

        .strategy-brrr { background: var(--accent-dim); color: var(--accent); }
        .strategy-cash_flow { background: var(--blue-dim); color: var(--blue); }
        .strategy-flip { background: var(--gold-dim); color: var(--gold); }

        .deal-metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 0.5rem;
        }

        .metric-cell {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border);
            border-radius: var(--radius-xs);
            padding: 0.6rem 0.75rem;
        }

        .metric-label {
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: var(--text-muted);
            font-weight: 600;
            margin-bottom: 0.2rem;
        }

        .metric-value {
            font-weight: 600;
            font-size: 0.92rem;
            color: var(--text-primary);
        }

        /* ── Analysis Results ── */
        .analysis-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            margin-top: 1rem;
            animation: fadeUp 0.35s ease backwards;
        }

        .analysis-top {
            display: flex;
            align-items: center;
            gap: 1.25rem;
            margin-bottom: 1rem;
        }

        .analysis-summary {
            font-size: 0.85rem;
            color: var(--text-secondary);
            line-height: 1.65;
            white-space: pre-wrap;
            font-family: 'DM Sans', sans-serif;
        }

        /* ── Offer Section ── */
        .offer-result {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            margin-top: 1rem;
            animation: fadeUp 0.35s ease backwards;
        }

        .offer-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }

        .offer-price-big {
            font-family: 'Playfair Display', serif;
            font-size: 1.8rem;
            font-weight: 600;
            color: var(--accent);
        }

        .offer-discount {
            font-size: 0.82rem;
            padding: 0.3rem 0.7rem;
            border-radius: 999px;
            background: var(--red-dim);
            color: var(--red);
            font-weight: 600;
        }

        /* ── Loading Spinner ── */
        .spinner-wrap {
            display: none;
            flex-direction: column;
            align-items: center;
            gap: 1rem;
            padding: 3rem;
        }

        .spinner-wrap.visible {
            display: flex;
        }

        .spinner {
            width: 32px;
            height: 32px;
            border: 3px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.7s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .spinner-text {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        /* ── Empty State ── */
        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-muted);
        }

        .empty-icon {
            font-size: 2.5rem;
            margin-bottom: 1rem;
            opacity: 0.3;
        }

        .empty-state p {
            font-size: 0.9rem;
            max-width: 320px;
            margin: 0 auto;
            line-height: 1.6;
        }

        /* ── Responsive ── */
        @media (max-width: 900px) {
            .app-layout {
                grid-template-columns: 1fr;
            }
            .sidebar {
                position: relative;
                height: auto;
                flex-direction: row;
                flex-wrap: wrap;
                padding: 1rem;
                gap: 0.5rem;
            }
            .nav { flex-direction: row; flex-wrap: wrap; }
            .sidebar-footer { display: none; }
            .main { padding: 1.5rem; }
            .stats-grid { grid-template-columns: 1fr; }
        }

        /* ── Scrollbar ── */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.14); }

        /* ── Staggered card animations ── */
        .deal-card:nth-child(1) { animation-delay: 0s; }
        .deal-card:nth-child(2) { animation-delay: 0.06s; }
        .deal-card:nth-child(3) { animation-delay: 0.12s; }
        .deal-card:nth-child(4) { animation-delay: 0.18s; }
        .deal-card:nth-child(5) { animation-delay: 0.24s; }
        .deal-card:nth-child(6) { animation-delay: 0.30s; }
        .deal-card:nth-child(7) { animation-delay: 0.36s; }
        .deal-card:nth-child(8) { animation-delay: 0.42s; }

        .analysis-card:nth-child(1) { animation-delay: 0s; }
        .analysis-card:nth-child(2) { animation-delay: 0.08s; }
        .analysis-card:nth-child(3) { animation-delay: 0.16s; }

        /* ── DOM Badge ── */
        .dom-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
        .dom-green { background: var(--accent-dim); color: var(--accent); }
        .dom-yellow { background: var(--gold-dim); color: var(--gold); }
        .dom-red { background: var(--red-dim); color: var(--red); }

        /* ── Room Potential Badge ── */
        .room-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            padding: 0.2rem 0.6rem;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
        .room-strong { background: var(--accent-dim); color: var(--accent); }
        .room-likely { background: var(--gold-dim); color: var(--gold); }

        /* ── Property Details Collapsible ── */
        .property-details {
            display: none;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 0.5rem;
            margin-top: 0.75rem;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border);
        }
        .property-details.open { display: grid; }
        .details-toggle {
            background: none;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            font-size: 0.75rem;
            font-family: 'DM Sans', sans-serif;
            cursor: pointer;
            padding: 0.3rem 0.7rem;
            border-radius: var(--radius-xs);
            transition: all 0.2s ease;
        }
        .details-toggle:hover {
            color: var(--text-primary);
            border-color: var(--border-hover);
        }

        /* ── Points Table ── */
        .points-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
            font-size: 0.8rem;
        }
        .points-table th {
            text-align: left;
            padding: 0.5rem 0.6rem;
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: var(--text-muted);
            font-weight: 600;
            border-bottom: 1px solid var(--border);
        }
        .points-table td {
            padding: 0.5rem 0.6rem;
            border-bottom: 1px solid var(--border);
            color: var(--text-secondary);
        }
        .points-table tr:hover td { color: var(--text-primary); }
        .points-table .row-highlight td { color: var(--accent); font-weight: 600; }

        /* ── DOM Adjusted Price ── */
        .dom-adjusted {
            font-size: 0.85rem;
            color: var(--gold);
            margin-top: 0.25rem;
        }
    </style>
</head>
<body>
<div class="app-layout">

    <!-- ── Sidebar ── -->
    <aside class="sidebar">
        <div class="logo">
            <div class="logo-icon">IQ</div>
            <div class="logo-text">Listing<span>IQ</span></div>
        </div>

        <nav class="nav">
            <div class="nav-label">Workspace</div>
            <div class="nav-item active" data-page="analyze" onclick="showPage('analyze')">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
                Analyze
            </div>
            <div class="nav-item" data-page="scanner" onclick="showPage('scanner')">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                Deal Scanner
            </div>
            <div class="nav-item" data-page="offer" onclick="showPage('offer')">
                <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                Offer Calculator
            </div>
        </nav>

        <div class="sidebar-footer">
            <div class="version-badge">
                <span class="version-dot"></span>
                ListingIQ v0.2.0
            </div>
        </div>
    </aside>

    <!-- ── Main Content ── -->
    <main class="main">

        <!-- ═══ ANALYZE PAGE ═══ -->
        <div class="page-section active" id="page-analyze">
            <div class="page-header">
                <h1>Property Analysis</h1>
                <p>Run a quick BRRR, cash flow, and flip analysis on any property.</p>
            </div>

            <div class="glass-card" style="margin-bottom: 2rem;">
                <div class="section-header">
                    <div class="section-title">Property Details</div>
                </div>
                <div class="form-grid">
                    <div class="field">
                        <label>Price ($)</label>
                        <input type="number" id="a-price" placeholder="250,000" value="250000">
                    </div>
                    <div class="field">
                        <label>Sq Ft</label>
                        <input type="number" id="a-sqft" placeholder="1,500" value="1500">
                    </div>
                    <div class="field">
                        <label>Beds</label>
                        <input type="number" id="a-beds" placeholder="3" value="3">
                    </div>
                    <div class="field">
                        <label>Baths</label>
                        <input type="number" id="a-baths" placeholder="2" value="2">
                    </div>
                    <div class="field">
                        <label>Annual Tax</label>
                        <input type="number" id="a-tax" placeholder="3,000" value="3000">
                    </div>
                    <div class="field">
                        <label>Monthly HOA</label>
                        <input type="number" id="a-hoa" placeholder="0" value="0">
                    </div>
                </div>
                <div class="section-header" style="margin-top:1.5rem;">
                    <div class="section-title">Market Estimates</div>
                    <span style="font-size:0.78rem;color:var(--text-muted);">Optional — leave blank to auto-estimate</span>
                </div>
                <div class="form-grid">
                    <div class="field">
                        <label>City</label>
                        <input type="text" id="a-city" placeholder="Austin">
                    </div>
                    <div class="field">
                        <label>State</label>
                        <input type="text" id="a-state" placeholder="TX" maxlength="2">
                    </div>
                    <div class="field">
                        <label>Est. Monthly Rent ($)</label>
                        <input type="number" id="a-rent" placeholder="Auto-estimate">
                    </div>
                    <div class="field">
                        <label>Est. ARV ($)</label>
                        <input type="number" id="a-arv" placeholder="Auto-estimate">
                    </div>
                </div>
                <div class="btn-row">
                    <button class="btn btn-primary" onclick="analyzeProperty()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                        Run Analysis
                    </button>
                </div>
            </div>

            <div id="analysis-results"></div>
        </div>

        <!-- ═══ SCANNER PAGE ═══ -->
        <div class="page-section" id="page-scanner">
            <div class="page-header">
                <h1>Deal Scanner</h1>
                <p>Scan MLS listings to surface high-potential investment deals.</p>
            </div>

            <div class="glass-card" style="margin-bottom: 2rem;">
                <div class="section-header">
                    <div class="section-title">Scan Parameters</div>
                </div>
                <div class="form-grid">
                    <div class="field" style="grid-column: span 2;">
                        <label>Market</label>
                        <input type="text" id="market" placeholder="Houston, TX" value="Houston, TX">
                    </div>
                    <div class="field">
                        <label>Source</label>
                        <select id="source">
                            <option value="repliers">Repliers</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>Min Score</label>
                        <input type="number" id="min-score" placeholder="50" value="50" min="0" max="100">
                    </div>
                </div>
                <div class="btn-row">
                    <button class="btn btn-primary" onclick="runScan()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                        Scan for Deals
                    </button>
                </div>
            </div>

            <div class="stats-grid" id="stats" style="display:none;">
                <div class="stat-card">
                    <div class="stat-label">Listings Scanned</div>
                    <div class="stat-value" id="stat-listings">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Deals Found</div>
                    <div class="stat-value" id="stat-deals">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Top Score</div>
                    <div class="stat-value" id="stat-best">&mdash;</div>
                </div>
            </div>

            <div class="spinner-wrap" id="loading">
                <div class="spinner"></div>
                <div class="spinner-text">Scanning listings across MLS sources...</div>
            </div>

            <div class="deals-list" id="deals"></div>
        </div>

        <!-- ═══ OFFER CALCULATOR PAGE ═══ -->
        <div class="page-section" id="page-offer">
            <div class="page-header">
                <h1>Offer Calculator</h1>
                <p>Work backwards from your target return to find the max offer price.</p>
            </div>

            <div class="glass-card" style="margin-bottom: 2rem;">
                <div class="section-header">
                    <div class="section-title">Property &amp; Targets</div>
                </div>
                <div class="form-grid">
                    <div class="field">
                        <label>List Price ($)</label>
                        <input type="number" id="o-price" placeholder="300,000" value="300000">
                    </div>
                    <div class="field">
                        <label>Sq Ft</label>
                        <input type="number" id="o-sqft" placeholder="1,500" value="1500">
                    </div>
                    <div class="field">
                        <label>Beds</label>
                        <input type="number" id="o-beds" placeholder="3" value="3">
                    </div>
                    <div class="field">
                        <label>Baths</label>
                        <input type="number" id="o-baths" placeholder="2" value="2">
                    </div>
                    <div class="field">
                        <label>Annual Tax</label>
                        <input type="number" id="o-tax" placeholder="3,000" value="3000">
                    </div>
                    <div class="field">
                        <label>Monthly HOA</label>
                        <input type="number" id="o-hoa" placeholder="0" value="0">
                    </div>
                    <div class="field">
                        <label>Strategy</label>
                        <select id="o-strategy">
                            <option value="">All Strategies</option>
                            <option value="brrr">BRRR</option>
                            <option value="cash_flow">Cash Flow</option>
                            <option value="flip">Flip</option>
                        </select>
                    </div>
                </div>
                <div class="section-header" style="margin-top:1.5rem;">
                    <div class="section-title">Market Estimates</div>
                    <span style="font-size:0.78rem;color:var(--text-muted);">Optional — leave blank to auto-estimate</span>
                </div>
                <div class="form-grid">
                    <div class="field">
                        <label>City</label>
                        <input type="text" id="o-city" placeholder="Austin">
                    </div>
                    <div class="field">
                        <label>State</label>
                        <input type="text" id="o-state" placeholder="TX" maxlength="2">
                    </div>
                    <div class="field">
                        <label>Est. Monthly Rent ($)</label>
                        <input type="number" id="o-rent" placeholder="Auto-estimate">
                    </div>
                    <div class="field">
                        <label>Est. ARV ($)</label>
                        <input type="number" id="o-arv" placeholder="Auto-estimate">
                    </div>
                </div>
                <div class="btn-row">
                    <button class="btn btn-primary" onclick="calcOffer()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                        Calculate Offer
                    </button>
                </div>
            </div>

            <div id="offer-results"></div>
        </div>

    </main>
</div>

<script>
    /* ── Navigation ── */
    function showPage(page) {
        document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        document.getElementById('page-' + page).classList.add('active');
        document.querySelector(`[data-page="${page}"]`).classList.add('active');
    }

    /* ── Score Ring SVG Builder ── */
    function scoreRingSvg(score) {
        const r = 23, c = 2 * Math.PI * r;
        const pct = Math.max(0, Math.min(100, score)) / 100;
        const offset = c * (1 - pct);
        let color = '#f87171';
        if (score >= 80) color = '#34d399';
        else if (score >= 60) color = '#f5c842';
        return `<svg class="score-ring" viewBox="0 0 56 56">
            <circle cx="28" cy="28" r="${r}" class="score-ring-bg"/>
            <circle cx="28" cy="28" r="${r}" class="score-ring-fill"
                stroke="${color}" stroke-dasharray="${c}" stroke-dashoffset="${offset}"/>
            <text x="28" y="28" class="score-ring-text">${score}</text>
        </svg>`;
    }

    /* ── Format metric values ── */
    function fmtMetric(k, v) {
        if (typeof v !== 'number') return v;
        if (k.includes('pct') || k.includes('rate') || k.includes('return') || k === 'roi' || k === 'cap_rate' || k === 'coc_return')
            return v.toFixed(1) + '%';
        if (k === 'dscr' || k === 'grm') return v.toFixed(1) + (k === 'dscr' ? 'x' : '');
        return '$' + v.toLocaleString('en-US', {maximumFractionDigits: 0});
    }

    function prettyLabel(k) {
        return k.replace(/_/g, ' ').replace(/\\b[a-z]/g, l => l.toUpperCase());
    }

    function strategyClass(s) {
        return 'strategy-' + s.toLowerCase().replace(/\\s+/g, '_');
    }

    /* ── DOM Badge ── */
    function domBadgeHtml(days) {
        if (days === undefined || days === null || days <= 0) return '';
        let cls = 'dom-green';
        if (days >= 60) cls = 'dom-red';
        else if (days >= 30) cls = 'dom-yellow';
        return `<span class="dom-badge ${cls}">${days} DOM</span>`;
    }

    /* ── Room Potential Badge ── */
    function roomBadgeHtml(rp) {
        if (!rp || rp.potential === 'none') return '';
        const cls = rp.potential === 'strong' ? 'room-strong' : 'room-likely';
        const icon = rp.potential === 'strong' ? '+' : '~';
        return `<span class="room-badge ${cls}">${icon} Room Potential</span>`;
    }

    /* ── Secondary Data Panel ── */
    function secondaryPanelHtml(sec, id) {
        if (!sec) return '';
        const items = [];
        if (sec.year_built) items.push({l: 'Year Built', v: sec.year_built});
        if (sec.lot_sqft) items.push({l: 'Lot SqFt', v: sec.lot_sqft.toLocaleString()});
        if (sec.tax_annual) items.push({l: 'Annual Tax', v: '$' + Number(sec.tax_annual).toLocaleString()});
        if (sec.stories) items.push({l: 'Stories', v: sec.stories});
        if (sec.has_pool !== null && sec.has_pool !== undefined) items.push({l: 'Pool', v: sec.has_pool ? 'Yes' : 'No'});
        if (sec.school_rating !== null && sec.school_rating !== undefined) items.push({l: 'School Rating', v: sec.school_rating + '/10'});
        if (sec.flood_zone) items.push({l: 'Flood Zone', v: sec.flood_zone});
        if (sec.crime_score !== null && sec.crime_score !== undefined) items.push({l: 'Crime Score', v: sec.crime_score});
        if (!items.length) return '';
        const cells = items.map(i => `<div class="metric-cell"><div class="metric-label">${i.l}</div><div class="metric-value">${i.v}</div></div>`).join('');
        return `<button class="details-toggle" onclick="document.getElementById('${id}').classList.toggle('open')">Property Details</button>
            <div class="property-details" id="${id}">${cells}</div>`;
    }

    /* ── Points Table ── */
    function pointsTableHtml(pts) {
        if (!pts || !pts.length) return '';
        const rows = pts.map(p =>
            `<tr class="${p.points === 0 ? 'row-highlight' : ''}">
                <td>${p.points}</td>
                <td>${(p.rate * 100).toFixed(2)}%</td>
                <td>$${p.monthly_payment.toLocaleString('en-US', {maximumFractionDigits: 0})}</td>
                <td>$${p.point_cost.toLocaleString('en-US', {maximumFractionDigits: 0})}</td>
                <td>${p.break_even_months ? p.break_even_months + ' mo' : '--'}</td>
                <td>$${p.total_interest.toLocaleString('en-US', {maximumFractionDigits: 0})}</td>
            </tr>`
        ).join('');
        return `<div style="margin-top:1rem;">
            <button class="details-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">Points Comparison</button>
            <div style="display:none;">
                <table class="points-table">
                    <thead><tr><th>Points</th><th>Rate</th><th>Payment</th><th>Cost</th><th>Break-Even</th><th>Total Interest</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>`;
    }

    /* ── Deal Scanner ── */
    async function runScan() {
        const market = document.getElementById('market').value;
        const source = document.getElementById('source').value;
        const minScore = document.getElementById('min-score').value;

        document.getElementById('loading').classList.add('visible');
        document.getElementById('deals').innerHTML = '';
        document.getElementById('stats').style.display = 'none';

        try {
            const resp = await fetch(
                `/api/scan?market=${encodeURIComponent(market)}&source=${source}&min_score=${minScore}`
            );
            const data = await resp.json();

            if (data.error) {
                document.getElementById('deals').innerHTML =
                    `<div class="glass-card"><p style="color:var(--red)">${data.error}</p></div>`;
                return;
            }

            document.getElementById('stat-listings').textContent = data.total_listings.toLocaleString();
            document.getElementById('stat-deals').textContent = data.qualifying_deals;
            document.getElementById('stat-best').textContent =
                data.deals.length ? data.deals[0].score : '\\u2014';
            document.getElementById('stats').style.display = 'grid';

            renderDeals(data.deals);
        } catch (e) {
            document.getElementById('deals').innerHTML =
                `<div class="glass-card"><p style="color:var(--red)">Error: ${e.message}</p></div>`;
        } finally {
            document.getElementById('loading').classList.remove('visible');
        }
    }

    function renderDeals(deals) {
        const container = document.getElementById('deals');
        if (!deals.length) {
            container.innerHTML = `<div class="empty-state">
                <div class="empty-icon">&#x1F50D;</div>
                <p>No deals matching your criteria. Try lowering the minimum score or scanning a different market.</p>
            </div>`;
            return;
        }

        container.innerHTML = deals.map((deal, i) => {
            const metrics = deal.metrics;
            const metricHtml = Object.entries(metrics).map(([k, v]) =>
                `<div class="metric-cell">
                    <div class="metric-label">${prettyLabel(k)}</div>
                    <div class="metric-value">${fmtMetric(k, v)}</div>
                </div>`
            ).join('');

            const strat = deal.strategy.replace('_', ' ');

            return `<div class="deal-card" style="animation-delay:${i * 0.06}s">
                <div class="deal-top">
                    ${scoreRingSvg(deal.score)}
                    <div class="deal-info">
                        <div class="deal-address">
                            ${deal.url ? `<a href="${deal.url}" target="_blank" rel="noopener">${deal.address}</a>` : deal.address}
                        </div>
                        <div class="deal-meta">
                            <span>$${deal.price.toLocaleString()}</span>
                            <span class="deal-meta-sep"></span>
                            <span>${deal.beds}bd / ${deal.baths}ba</span>
                            <span class="deal-meta-sep"></span>
                            <span>${deal.sqft ? deal.sqft.toLocaleString() + ' sqft' : 'N/A'}</span>
                            ${domBadgeHtml(deal.days_on_market)}
                            ${roomBadgeHtml(deal.room_potential)}
                        </div>
                    </div>
                    <span class="strategy-tag ${strategyClass(deal.strategy)}">${strat}</span>
                </div>
                <div class="deal-metrics-grid">${metricHtml}</div>
                ${secondaryPanelHtml(deal.secondary, 'sec-deal-' + i)}
            </div>`;
        }).join('');
    }

    /* ── Property Analysis ── */
    async function analyzeProperty() {
        const price = document.getElementById('a-price').value;
        const sqft = document.getElementById('a-sqft').value;
        const beds = document.getElementById('a-beds').value;
        const baths = document.getElementById('a-baths').value;
        const tax = document.getElementById('a-tax').value;
        const hoa = document.getElementById('a-hoa').value;
        const city = document.getElementById('a-city').value;
        const state = document.getElementById('a-state').value;
        const rent = document.getElementById('a-rent').value;
        const arv = document.getElementById('a-arv').value;

        const container = document.getElementById('analysis-results');
        container.innerHTML = `<div class="spinner-wrap visible"><div class="spinner"></div><div class="spinner-text">Analyzing property...</div></div>`;

        try {
            let url = `/api/analyze?price=${price}&sqft=${sqft}&beds=${beds}&baths=${baths}&tax=${tax}&hoa=${hoa}`;
            if (city) url += `&city=${encodeURIComponent(city)}`;
            if (state) url += `&state=${encodeURIComponent(state)}`;
            if (rent) url += `&rent=${rent}`;
            if (arv) url += `&arv=${arv}`;
            const resp = await fetch(url);
            const data = await resp.json();

            let compHtml = '';
            if (data.comps && Object.keys(data.comps).length > 0) {
                const c = data.comps;
                const items = [];
                if (c.rent_used) items.push(`<span>Rent used: <strong>$${Number(c.rent_used).toLocaleString()}/mo</strong></span>`);
                if (c.rent_estimate && c.rent_used && c.rent_estimate !== c.rent_used) items.push(`<span style="color:var(--text-muted)">(Comp est: $${Number(c.rent_estimate).toLocaleString()}/mo, ${c.rent_confidence || '?'} conf.)</span>`);
                if (c.arv_used) items.push(`<span>ARV used: <strong>$${Number(c.arv_used).toLocaleString()}</strong></span>`);
                if (c.arv_estimate && c.arv_used && c.arv_estimate !== c.arv_used) items.push(`<span style="color:var(--text-muted)">(Comp est: $${Number(c.arv_estimate).toLocaleString()}, ${c.arv_confidence || '?'} conf.)</span>`);
                if (items.length) {
                    compHtml = `<div class="glass-card" style="margin-bottom:1rem;padding:0.75rem 1rem;font-size:0.82rem;display:flex;flex-wrap:wrap;gap:0.75rem;align-items:center;">
                        <span style="color:var(--accent);font-weight:600;">Estimates</span>${items.join('')}
                    </div>`;
                }
            }

            let rpHtml = '';
            if (data.room_potential && data.room_potential.potential !== 'none') {
                rpHtml = roomBadgeHtml(data.room_potential);
                if (data.room_potential.description) {
                    rpHtml += `<span style="font-size:0.78rem;color:var(--text-secondary);margin-left:0.5rem;">${data.room_potential.description}</span>`;
                }
                rpHtml = `<div class="glass-card" style="margin-bottom:1rem;padding:0.75rem 1rem;display:flex;flex-wrap:wrap;align-items:center;gap:0.5rem;">` + rpHtml + `</div>`;
            }

            let domHtml = '';
            if (data.days_on_market > 0) {
                domHtml = `<div class="glass-card" style="margin-bottom:1rem;padding:0.75rem 1rem;display:flex;align-items:center;gap:0.75rem;font-size:0.82rem;">
                    ${domBadgeHtml(data.days_on_market)}
                    <span style="color:var(--text-secondary);">Days on market</span>
                </div>`;
            }

            let secHtml = secondaryPanelHtml(data.secondary, 'sec-analyze');
            if (secHtml) {
                secHtml = `<div class="glass-card" style="margin-bottom:1rem;padding:0.75rem 1rem;">${secHtml}</div>`;
            }

            container.innerHTML = compHtml + rpHtml + domHtml + secHtml + data.analyses.map((a, i) => {
                const strat = a.strategy.replace('_', ' ');
                return `<div class="analysis-card" style="animation-delay:${i * 0.08}s">
                    <div class="analysis-top">
                        ${scoreRingSvg(a.score)}
                        <div style="flex:1">
                            <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.25rem;">
                                <span style="font-weight:600;font-size:1rem;">${prettyLabel(strat)}</span>
                                <span class="strategy-tag ${strategyClass(a.strategy)}">${a.meets_criteria ? 'Meets Criteria' : 'Below Target'}</span>
                            </div>
                        </div>
                    </div>
                    <div class="analysis-summary">${a.summary}</div>
                </div>`;
            }).join('');
        } catch (e) {
            container.innerHTML = `<div class="glass-card"><p style="color:var(--red)">Error: ${e.message}</p></div>`;
        }
    }

    /* ── Offer Calculator ── */
    async function calcOffer() {
        const price = document.getElementById('o-price').value;
        const sqft = document.getElementById('o-sqft').value;
        const beds = document.getElementById('o-beds').value;
        const baths = document.getElementById('o-baths').value;
        const tax = document.getElementById('o-tax').value;
        const hoa = document.getElementById('o-hoa').value;
        const strategy = document.getElementById('o-strategy').value;
        const city = document.getElementById('o-city').value;
        const state = document.getElementById('o-state').value;
        const rent = document.getElementById('o-rent').value;
        const arv = document.getElementById('o-arv').value;

        const container = document.getElementById('offer-results');
        container.innerHTML = `<div class="spinner-wrap visible"><div class="spinner"></div><div class="spinner-text">Calculating optimal offer prices...</div></div>`;

        let url = `/api/offer-price?price=${price}&sqft=${sqft}&beds=${beds}&baths=${baths}&tax=${tax}&hoa=${hoa}`;
        if (strategy) url += `&strategy=${strategy}`;
        if (city) url += `&city=${encodeURIComponent(city)}`;
        if (state) url += `&state=${encodeURIComponent(state)}`;
        if (rent) url += `&rent=${rent}`;
        if (arv) url += `&arv=${arv}`;

        try {
            const resp = await fetch(url);
            const data = await resp.json();

            container.innerHTML = data.offers.map((o, i) => {
                const strat = o.strategy.replace('_', ' ');
                const discount = o.discount_from_list.toFixed(1);
                const metricsHtml = o.metrics_at_offer ? Object.entries(o.metrics_at_offer).map(([k, v]) =>
                    `<div class="metric-cell">
                        <div class="metric-label">${prettyLabel(k)}</div>
                        <div class="metric-value">${fmtMetric(k, v)}</div>
                    </div>`
                ).join('') : '';

                const domAdj = o.dom_adjusted_price && o.dom_adjusted_price !== o.max_offer_price
                    ? `<div class="dom-adjusted">DOM-Adjusted: $${o.dom_adjusted_price.toLocaleString('en-US', {maximumFractionDigits: 0})}</div>`
                    : '';

                return `<div class="offer-result" style="animation-delay:${i * 0.08}s">
                    <div class="offer-header">
                        <div>
                            <span class="strategy-tag ${strategyClass(o.strategy)}" style="margin-right:0.5rem">${strat}</span>
                            <span style="color:var(--text-secondary);font-size:0.82rem;">
                                Target: ${prettyLabel(o.target_metric)} &ge; ${o.target_value}
                            </span>
                        </div>
                        <span class="offer-discount">${discount}% below list</span>
                    </div>
                    <div class="offer-price-big">$${o.max_offer_price.toLocaleString('en-US', {maximumFractionDigits: 0})}</div>
                    ${domAdj}
                    <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:1rem;">
                        Max offer to hit your target return
                    </div>
                    ${metricsHtml ? `<div class="deal-metrics-grid">${metricsHtml}</div>` : ''}
                    ${pointsTableHtml(o.points_table)}
                </div>`;
            }).join('');

            if (!data.offers.length) {
                container.innerHTML = `<div class="empty-state">
                    <div class="empty-icon">&#x1F4B0;</div>
                    <p>No viable offer found. The target return may not be achievable at any price for this property.</p>
                </div>`;
            }
        } catch (e) {
            container.innerHTML = `<div class="glass-card"><p style="color:var(--red)">Error: ${e.message}</p></div>`;
        }
    }
</script>
</body>
</html>"""


# Module-level app instance for uvicorn (e.g. Railway deployment)
app = create_app(load_config())

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
