"""Scheduler for periodic MLS scanning and deal analysis."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from listingiq.config import AppConfig
from listingiq.models import Listing
from listingiq.scrapers import get_scraper
from listingiq.analysis.engine import DealAnalyzer
from listingiq.alerts.dispatcher import AlertDispatcher
from listingiq.db.repository import Repository

logger = logging.getLogger(__name__)


async def _run_cycle(cfg: AppConfig) -> None:
    """Execute one full scrape -> analyze -> alert cycle."""
    logger.info("Starting scan cycle at %s", datetime.utcnow().isoformat())

    repo = Repository(cfg.database.url)
    all_listings: list[Listing] = []

    # Use watchlist entries if available, otherwise configured markets
    watchlist = repo.get_watchlist()
    if watchlist:
        markets = [entry.query for entry in watchlist]
        logger.info("Using %d watchlist areas", len(markets))
    else:
        markets = cfg.scraper.search.markets

    # Scrape all sources
    for source_name in cfg.scraper.sources:
        try:
            scraper_cls = get_scraper(source_name)
            scraper_cfg = cfg.scraper.model_copy(deep=True)
            scraper_cfg.search.markets = markets
            scraper = scraper_cls(scraper_cfg)
            listings = await scraper.scrape()
            all_listings.extend(listings)
            logger.info("%s: found %d listings", source_name, len(listings))
            await scraper.close()
        except Exception as e:
            logger.error("Error scraping %s: %s", source_name, e)

    # Deduplicate by source_id (overlapping areas may return same listing)
    seen_ids: set[str] = set()
    unique_listings: list[Listing] = []
    for listing in all_listings:
        if listing.source_id not in seen_ids:
            seen_ids.add(listing.source_id)
            unique_listings.append(listing)
    all_listings = unique_listings

    if not all_listings:
        logger.warning("No listings found this cycle")
        return

    # Store listings
    for listing in all_listings:
        repo.upsert_listing(listing)

    logger.info("Stored %d listings", len(all_listings))

    # Analyze
    analyzer = DealAnalyzer(cfg.analysis)
    deals = analyzer.get_top_deals(
        all_listings,
        min_score=cfg.alerts.min_deal_score,
    )

    if not deals:
        logger.info("No deals meet criteria this cycle")
        return

    logger.info("Found %d qualifying deals", len(deals))

    # Store deals
    for deal in deals:
        listing_id = repo.upsert_listing(deal.listing)
        repo.save_deal(listing_id, deal)

    # Alert
    dispatcher = AlertDispatcher(cfg.alerts)
    alerts = await dispatcher.dispatch(deals)
    logger.info("Sent %d alerts", len(alerts))


def _run_cycle_sync(cfg: AppConfig) -> None:
    """Synchronous wrapper for the async cycle."""
    asyncio.run(_run_cycle(cfg))


async def _run_digest(cfg: AppConfig) -> None:
    """Send a digest email with recent qualifying deals."""
    from datetime import timedelta
    from listingiq.alerts.channels import EmailChannel

    repo = Repository(cfg.database.url)
    if cfg.alerts.digest.schedule == "daily":
        since = datetime.utcnow() - timedelta(days=1)
    else:
        since = datetime.utcnow() - timedelta(weeks=1)

    deal_rows = repo.get_deals_since(since, min_score=cfg.alerts.digest.min_score)
    if not deal_rows:
        logger.info("No deals for digest")
        return

    from listingiq.models import DealAnalysis, DealStrategy
    deals = []
    for row in deal_rows:
        listing_row = repo.get_listing_by_id(row.listing_id)
        if not listing_row:
            continue
        listing = Listing(
            source=listing_row.source, source_id=listing_row.source_id,
            address=listing_row.address, city=listing_row.city,
            state=listing_row.state, zip_code=listing_row.zip_code,
            price=listing_row.price, beds=listing_row.beds,
            baths=listing_row.baths, sqft=listing_row.sqft,
        )
        deal = DealAnalysis(
            listing=listing,
            strategy=DealStrategy(row.strategy),
            score=row.score,
            metrics=row.metrics or {},
            meets_criteria=row.meets_criteria,
            summary=row.summary or "",
        )
        deals.append(deal)

    if deals and cfg.alerts.email.smtp_host:
        channel = EmailChannel(cfg.alerts.email)
        await channel.send_digest(deals)
        logger.info("Digest sent with %d deals", len(deals))


def _run_digest_sync(cfg: AppConfig) -> None:
    asyncio.run(_run_digest(cfg))


def start_scheduler(cfg: AppConfig) -> None:
    """Start the blocking scheduler."""
    scheduler = BlockingScheduler()

    scheduler.add_job(
        _run_cycle_sync,
        trigger=IntervalTrigger(minutes=cfg.scraper.interval_minutes),
        args=[cfg],
        id="scan_cycle",
        name="MLS Scan Cycle",
        next_run_time=datetime.now(),  # Run immediately on start
    )

    # Add digest job if configured
    if cfg.alerts.digest.enabled and "email" in cfg.alerts.channels:
        from apscheduler.triggers.cron import CronTrigger

        hour, minute = cfg.alerts.digest.time.split(":")
        if cfg.alerts.digest.schedule == "daily":
            trigger = CronTrigger(hour=int(hour), minute=int(minute))
        else:  # weekly
            trigger = CronTrigger(day_of_week="mon", hour=int(hour), minute=int(minute))

        scheduler.add_job(
            _run_digest_sync,
            trigger=trigger,
            args=[cfg],
            id="digest_email",
            name="Deal Digest Email",
        )
        logger.info("Digest email scheduled: %s at %s", cfg.alerts.digest.schedule, cfg.alerts.digest.time)

    logger.info(
        "Scheduler started. Scanning every %d minutes.",
        cfg.scraper.interval_minutes,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
        scheduler.shutdown()
