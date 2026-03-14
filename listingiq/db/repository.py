"""Database repository for storing and retrieving listings and deals."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from listingiq.db.tables import ListingRow, DealRow, AlertRow, WatchlistRow, init_db
from listingiq.models import Listing, DealAnalysis


class Repository:
    """Handles all database operations."""

    def __init__(self, db_url: str = "sqlite:///listingiq.db"):
        self._session_factory = init_db(db_url)

    def _session(self) -> Session:
        return self._session_factory()

    def upsert_listing(self, listing: Listing) -> int:
        """Insert or update a listing. Returns the row ID."""
        with self._session() as session:
            existing = (
                session.query(ListingRow)
                .filter_by(source=listing.source, source_id=listing.source_id)
                .first()
            )
            if existing:
                # Update existing listing
                price_changed = existing.price != listing.price
                if price_changed:
                    history = existing.price_history or []
                    history.append({"price": existing.price, "date": datetime.utcnow().isoformat()})
                    existing.price_history = history

                existing.price = listing.price
                existing.status = listing.status.value
                existing.days_on_market = listing.days_on_market
                existing.last_seen = datetime.utcnow()
                existing.raw_data = listing.raw_data
                session.commit()
                return existing.id
            else:
                row = ListingRow(
                    source=listing.source,
                    source_id=listing.source_id,
                    url=listing.url,
                    address=listing.address,
                    city=listing.city,
                    state=listing.state,
                    zip_code=listing.zip_code,
                    price=listing.price,
                    beds=listing.beds,
                    baths=listing.baths,
                    sqft=listing.sqft,
                    lot_sqft=listing.lot_sqft,
                    year_built=listing.year_built,
                    property_type=listing.property_type.value,
                    status=listing.status.value,
                    days_on_market=listing.days_on_market,
                    hoa_monthly=listing.hoa_monthly,
                    tax_annual=listing.tax_annual,
                    units=listing.units,
                    has_pool=listing.has_pool,
                    stories=listing.stories,
                    school_rating=listing.school_rating,
                    flood_zone=listing.flood_zone,
                    crime_score=listing.crime_score,
                    description=listing.description,
                    raw_data=listing.raw_data,
                    price_history=[],
                )
                session.add(row)
                session.commit()
                return row.id

    def save_deal(self, listing_id: int, deal: DealAnalysis) -> int:
        """Save a deal analysis result."""
        with self._session() as session:
            row = DealRow(
                listing_id=listing_id,
                strategy=deal.strategy.value,
                score=deal.score,
                metrics=deal.metrics,
                meets_criteria=deal.meets_criteria,
                summary=deal.summary,
            )
            session.add(row)
            session.commit()
            return row.id

    def mark_alerted(self, deal_id: int, channels: list[str]) -> None:
        """Mark a deal as alerted."""
        with self._session() as session:
            deal = session.query(DealRow).get(deal_id)
            if deal:
                deal.alerted = True
                deal.alerted_at = datetime.utcnow()
                session.commit()

            alert = AlertRow(deal_id=deal_id, channels=channels)
            session.add(alert)
            session.commit()

    def get_active_listings(self, city: str | None = None) -> list[ListingRow]:
        """Get all active listings, optionally filtered by city."""
        with self._session() as session:
            query = session.query(ListingRow).filter_by(status="active")
            if city:
                query = query.filter_by(city=city)
            return query.all()

    def get_top_deals(self, limit: int = 20, strategy: str | None = None) -> list[DealRow]:
        """Get the highest-scoring deals."""
        with self._session() as session:
            query = session.query(DealRow).filter_by(meets_criteria=True)
            if strategy:
                query = query.filter_by(strategy=strategy)
            return query.order_by(DealRow.score.desc()).limit(limit).all()

    def get_listing_by_id(self, listing_id: int) -> ListingRow | None:
        """Fetch a listing by its ID."""
        with self._session() as session:
            return session.query(ListingRow).get(listing_id)

    def get_deals_since(self, since: datetime, min_score: float = 0) -> list:
        """Get deals analyzed after a given timestamp."""
        with self._session() as session:
            return (
                session.query(DealRow)
                .filter(DealRow.analyzed_at >= since, DealRow.score >= min_score)
                .order_by(DealRow.score.desc())
                .all()
            )

    def listing_exists(self, source: str, source_id: str) -> bool:
        """Check if we've already seen this listing."""
        with self._session() as session:
            return (
                session.query(ListingRow)
                .filter_by(source=source, source_id=source_id)
                .first()
                is not None
            )

    def add_watchlist_entry(self, query: str, label: str | None = None) -> int | None:
        """Add a watchlist entry. Returns ID or None if duplicate."""
        with self._session() as session:
            existing = (
                session.query(WatchlistRow)
                .filter(WatchlistRow.query.ilike(query.strip()))
                .first()
            )
            if existing:
                return None
            row = WatchlistRow(query=query.strip(), label=label)
            session.add(row)
            session.commit()
            return row.id

    def delete_watchlist_entry(self, entry_id: int) -> bool:
        """Delete a watchlist entry by ID. Returns True if deleted."""
        with self._session() as session:
            row = session.query(WatchlistRow).get(entry_id)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    def get_watchlist(self) -> list[WatchlistRow]:
        """Get all watchlist entries ordered by creation date."""
        with self._session() as session:
            return (
                session.query(WatchlistRow)
                .order_by(WatchlistRow.created_at.asc())
                .all()
            )
