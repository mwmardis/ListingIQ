"""CLI interface for ListingIQ."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from listingiq.config import load_config
from listingiq.models import Listing

app = typer.Typer(
    name="listingiq",
    help="MLS Deal Alert System - Find profitable real estate investment deals.",
    no_args_is_help=True,
)
console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def scan(
    config_path: Path = typer.Option(None, "--config", "-c", help="Path to config TOML file"),
    market: str = typer.Option(None, "--market", "-m", help="Override market to scan"),
    source: str = typer.Option(None, "--source", "-s", help="Override scraper source"),
    strategy: str = typer.Option(None, "--strategy", help="Only run specific strategy"),
    min_score: int = typer.Option(None, "--min-score", help="Minimum deal score to display"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max deals to show"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    no_alert: bool = typer.Option(False, "--no-alert", help="Skip sending alerts"),
):
    """Scan MLS listings and analyze for deals."""
    setup_logging(verbose)
    cfg = load_config(config_path)

    # Apply overrides
    if market:
        cfg.scraper.search.markets = [market]
    if source:
        cfg.scraper.sources = [source]
    if strategy:
        cfg.analysis.strategies = [strategy]
    if min_score is not None:
        cfg.alerts.min_deal_score = min_score

    asyncio.run(_run_scan(cfg, limit, no_alert))


async def _run_scan(cfg, limit: int, no_alert: bool) -> None:
    from listingiq.scrapers import get_scraper
    from listingiq.analysis.engine import DealAnalyzer
    from listingiq.alerts.dispatcher import AlertDispatcher

    all_listings: list[Listing] = []

    # Scrape
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for source_name in cfg.scraper.sources:
            task = progress.add_task(f"Scraping {source_name}...", total=None)
            try:
                scraper_cls = get_scraper(source_name)
                scraper = scraper_cls(cfg.scraper)
                listings = await scraper.scrape()
                all_listings.extend(listings)
                progress.update(task, description=f"[green]{source_name}: {len(listings)} listings")
            except Exception as e:
                progress.update(task, description=f"[red]{source_name}: Error - {e}")
            finally:
                if hasattr(scraper, "close"):
                    await scraper.close()

    if not all_listings:
        console.print("[yellow]No listings found. Check your config and try again.[/yellow]")
        return

    console.print(f"\n[bold]Found {len(all_listings)} listings across {len(cfg.scraper.sources)} source(s)[/bold]\n")

    # Analyze
    analyzer = DealAnalyzer(cfg.analysis)
    deals = analyzer.get_top_deals(all_listings, min_score=cfg.alerts.min_deal_score, limit=limit)

    if not deals:
        console.print("[yellow]No deals meet your criteria. Try lowering min_score or adjusting parameters.[/yellow]")
        return

    console.print(f"[bold green]Found {len(deals)} deals meeting your criteria![/bold green]\n")

    # Display results
    _display_deals_table(deals)

    # Alert
    if not no_alert:
        dispatcher = AlertDispatcher(cfg.alerts)
        alerts = await dispatcher.dispatch(deals)
        if alerts:
            console.print(f"\n[bold]Sent {len(alerts)} alert(s)[/bold]")


def _display_deals_table(deals) -> None:
    """Display deals in a rich table."""
    table = Table(title="Top Deals", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", style="bold")
    table.add_column("Strategy", style="cyan")
    table.add_column("Address", style="white")
    table.add_column("Price", style="green")
    table.add_column("Beds/Bath", style="white")
    table.add_column("Key Metric", style="yellow")
    table.add_column("Source", style="dim")

    for i, deal in enumerate(deals, 1):
        listing = deal.listing
        strategy = deal.strategy.value.upper().replace("_", " ")

        # Pick the most relevant metric for the strategy
        key_metric = ""
        m = deal.metrics
        if deal.strategy.value == "brrr":
            key_metric = f"CoC: {m.get('cash_on_cash_return', 0):.1f}%"
        elif deal.strategy.value == "cash_flow":
            key_metric = f"CF: ${m.get('monthly_cash_flow', 0):,.0f}/mo"
        elif deal.strategy.value == "flip":
            key_metric = f"Profit: ${m.get('estimated_profit', 0):,.0f}"

        # Color-code score
        score_val = deal.score
        if score_val >= 80:
            score_str = f"[bold green]{score_val}[/bold green]"
        elif score_val >= 60:
            score_str = f"[bold yellow]{score_val}[/bold yellow]"
        else:
            score_str = f"{score_val}"

        table.add_row(
            str(i),
            score_str,
            strategy,
            listing.address[:35],
            f"${listing.price:,.0f}",
            f"{listing.beds}/{listing.baths}",
            key_metric,
            listing.source,
        )

    console.print(table)


@app.command()
def analyze(
    address: str = typer.Argument(..., help="Property address or listing URL"),
    price: float = typer.Option(..., "--price", "-p", help="Listing price"),
    beds: int = typer.Option(3, "--beds"),
    baths: float = typer.Option(2, "--baths"),
    sqft: int = typer.Option(1500, "--sqft"),
    tax: float = typer.Option(0, "--tax", help="Annual property tax"),
    hoa: float = typer.Option(0, "--hoa", help="Monthly HOA"),
    city: str = typer.Option("", "--city", help="City for comp lookup"),
    state: str = typer.Option("", "--state", help="State for comp lookup"),
    config_path: Path = typer.Option(None, "--config", "-c"),
):
    """Analyze a specific property for investment potential."""
    cfg = load_config(config_path)

    listing = Listing(
        source="manual",
        source_id="manual-entry",
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

    asyncio.run(_run_analyze(cfg, listing))


async def _run_analyze(cfg, listing: Listing) -> None:
    from listingiq.analysis.engine import DealAnalyzer
    from listingiq.comps.rental import RentalCompService
    from listingiq.comps.sales import SalesCompService

    rent_estimate = None
    arv_estimate = None

    # Fetch comps if enabled and we have location data
    if cfg.analysis.comps.enabled and listing.city:
        console.print("[dim]Fetching comparable data...[/dim]")

        rental_svc = RentalCompService(cfg.analysis.comps, cfg.scraper)
        sales_svc = SalesCompService(cfg.analysis.comps)

        try:
            rent, rental_comps, rent_conf = await rental_svc.estimate_rent(listing)
            rent_estimate = rent
            console.print(
                f"  Rent estimate: ${rent:,.0f}/mo "
                f"({len(rental_comps)} comps, {rent_conf} confidence)"
            )
        except Exception as e:
            console.print(f"  [yellow]Rental comps unavailable: {e}[/yellow]")
        finally:
            await rental_svc.close()

        try:
            arv, sales_comps, arv_conf = await sales_svc.estimate_arv(listing)
            arv_estimate = arv
            console.print(
                f"  ARV estimate: ${arv:,.0f} "
                f"({len(sales_comps)} comps, {arv_conf} confidence)"
            )
        except Exception as e:
            console.print(f"  [yellow]Sales comps unavailable: {e}[/yellow]")
        finally:
            await sales_svc.close()

        console.print()

    analyzer = DealAnalyzer(cfg.analysis)
    deals = analyzer.analyze_listing(
        listing, rent_estimate=rent_estimate, arv_estimate=arv_estimate
    )

    for deal in deals:
        console.print()
        console.print(Panel(deal.summary, title=f"{deal.strategy.value.upper()} - Score: {deal.score}"))


@app.command()
def offer_price(
    address: str = typer.Argument(..., help="Property address"),
    price: float = typer.Option(..., "--price", "-p", help="Current list price"),
    beds: int = typer.Option(3, "--beds"),
    baths: float = typer.Option(2, "--baths"),
    sqft: int = typer.Option(1500, "--sqft"),
    tax: float = typer.Option(0, "--tax", help="Annual property tax"),
    hoa: float = typer.Option(0, "--hoa", help="Monthly HOA"),
    city: str = typer.Option("", "--city", help="City for comp lookup"),
    state: str = typer.Option("", "--state", help="State for comp lookup"),
    strategy: str = typer.Option(None, "--strategy", help="Strategy to calculate for (default: all)"),
    target_metric: str = typer.Option(None, "--target-metric", help="Metric to target"),
    target_value: float = typer.Option(None, "--target-value", help="Desired value for target metric"),
    config_path: Path = typer.Option(None, "--config", "-c"),
):
    """Calculate the maximum offer price to achieve a target return.

    Works backwards from your desired return to tell you the most you should pay.
    """
    cfg = load_config(config_path)

    listing = Listing(
        source="manual",
        source_id="manual-entry",
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

    asyncio.run(_run_offer_price(cfg, listing, strategy, target_metric, target_value))


async def _run_offer_price(cfg, listing, strategy, target_metric, target_value) -> None:
    from listingiq.analysis.offer import OfferCalculator
    from listingiq.comps.rental import RentalCompService
    from listingiq.comps.sales import SalesCompService

    rent_estimate = None
    arv_estimate = None

    # Fetch comps if enabled
    if cfg.analysis.comps.enabled and listing.city:
        console.print("[dim]Fetching comparable data...[/dim]")

        rental_svc = RentalCompService(cfg.analysis.comps, cfg.scraper)
        sales_svc = SalesCompService(cfg.analysis.comps)

        try:
            rent, rental_comps, rent_conf = await rental_svc.estimate_rent(listing)
            rent_estimate = rent
            console.print(f"  Rent estimate: ${rent:,.0f}/mo ({rent_conf} confidence)")
        except Exception:
            pass
        finally:
            await rental_svc.close()

        try:
            arv, sales_comps, arv_conf = await sales_svc.estimate_arv(listing)
            arv_estimate = arv
            console.print(f"  ARV estimate: ${arv:,.0f} ({arv_conf} confidence)")
        except Exception:
            pass
        finally:
            await sales_svc.close()

        console.print()

    calculator = OfferCalculator(cfg.analysis)

    console.print(f"[bold]Offer Price Analysis for {listing.address}[/bold]")
    console.print(f"List Price: ${listing.price:,.0f}\n")

    if strategy:
        results = [calculator.calculate_offer_price(
            listing,
            strategy=strategy,
            target_metric=target_metric,
            target_value=target_value,
            rent_estimate=rent_estimate,
            arv_estimate=arv_estimate,
        )]
    else:
        results = calculator.calculate_all_offers(
            listing,
            rent_estimate=rent_estimate,
            arv_estimate=arv_estimate,
        )

    table = Table(title="Maximum Offer Prices", show_lines=True)
    table.add_column("Strategy", style="cyan")
    table.add_column("Target", style="white")
    table.add_column("Max Offer", style="bold green")
    table.add_column("Discount", style="yellow")
    table.add_column("Key Metric at Offer", style="white")

    for r in results:
        strategy_name = r.strategy.value.upper().replace("_", " ")
        target_str = f"{r.target_metric}: {r.target_value:,.0f}"
        if "return" in r.target_metric or "rate" in r.target_metric:
            target_str = f"{r.target_metric}: {r.target_value:.1f}%"

        # Pick the most relevant metric to show
        m = r.metrics_at_offer
        if r.strategy.value == "cash_flow":
            key = f"CF: ${m.get('monthly_cash_flow', 0):,.0f}/mo | CoC: {m.get('cash_on_cash_return', 0):.1f}%"
        elif r.strategy.value == "brrr":
            key = f"CoC: {m.get('cash_on_cash_return', 0):.1f}% | CF: ${m.get('monthly_cash_flow', 0):,.0f}/mo"
        elif r.strategy.value == "flip":
            key = f"Profit: ${m.get('estimated_profit', 0):,.0f} | ROI: {m.get('roi', 0):.1f}%"
        else:
            key = ""

        discount_str = f"{r.discount_from_list:.1f}% below list"

        table.add_row(
            strategy_name,
            target_str,
            f"${r.max_offer_price:,.0f}",
            discount_str,
            key,
        )

    console.print(table)


@app.command()
def watch(
    config_path: Path = typer.Option(None, "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Start the scheduler to periodically scan for deals."""
    setup_logging(verbose)
    cfg = load_config(config_path)

    from listingiq.scheduler import start_scheduler

    console.print(
        f"[bold]Starting ListingIQ watcher[/bold]\n"
        f"Markets: {', '.join(cfg.scraper.search.markets)}\n"
        f"Sources: {', '.join(cfg.scraper.sources)}\n"
        f"Interval: every {cfg.scraper.interval_minutes} minutes\n"
        f"Strategies: {', '.join(cfg.analysis.strategies)}\n"
        f"Alert channels: {', '.join(cfg.alerts.channels)}\n"
    )

    start_scheduler(cfg)


@app.command()
def config_show(
    config_path: Path = typer.Option(None, "--config", "-c"),
):
    """Display current configuration."""
    cfg = load_config(config_path)
    import json

    console.print_json(json.dumps(cfg.model_dump(), indent=2, default=str))


@app.command()
def serve(
    config_path: Path = typer.Option(None, "--config", "-c"),
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
):
    """Start the web dashboard API server."""
    import uvicorn

    cfg = load_config(config_path)

    from listingiq.api.server import create_app

    web_app = create_app(cfg)
    console.print(f"[bold]Starting ListingIQ dashboard at http://{host}:{port}[/bold]")
    uvicorn.run(web_app, host=host, port=port)


if __name__ == "__main__":
    app()
