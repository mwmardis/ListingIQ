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

    # Scrape all sources
    for source_name in cfg.scraper.sources:
        try:
            scraper_cls = get_scraper(source_name)
            scraper = scraper_cls(cfg.scraper)
            listings = await scraper.scrape()
            all_listings.extend(listings)
            logger.info("%s: found %d listings", source_name, len(listings))
            await scraper.close()
        except Exception as e:
            logger.error("Error scraping %s: %s", source_name, e)

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

    logger.info(
        "Scheduler started. Scanning every %d minutes.",
        cfg.scraper.interval_minutes,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
        scheduler.shutdown()
