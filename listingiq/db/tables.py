"""SQLAlchemy table definitions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Boolean,
    JSON,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class ListingRow(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_listing"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False, index=True)
    source_id = Column(String(100), nullable=False)
    url = Column(Text, default="")
    address = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False, index=True)
    state = Column(String(10), nullable=False, index=True)
    zip_code = Column(String(10), nullable=False)
    price = Column(Float, nullable=False, index=True)
    beds = Column(Integer, default=0)
    baths = Column(Float, default=0)
    sqft = Column(Integer, default=0)
    lot_sqft = Column(Integer, default=0)
    year_built = Column(Integer, default=0)
    property_type = Column(String(50), default="single_family")
    status = Column(String(20), default="active", index=True)
    days_on_market = Column(Integer, default=0)
    hoa_monthly = Column(Float, default=0.0)
    tax_annual = Column(Float, default=0.0)
    description = Column(Text, default="")
    raw_data = Column(JSON, default=dict)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    price_history = Column(JSON, default=list)


class DealRow(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, nullable=False, index=True)
    strategy = Column(String(20), nullable=False)
    score = Column(Float, default=0.0, index=True)
    metrics = Column(JSON, default=dict)
    meets_criteria = Column(Boolean, default=False)
    summary = Column(Text, default="")
    analyzed_at = Column(DateTime, default=datetime.utcnow)
    alerted = Column(Boolean, default=False)
    alerted_at = Column(DateTime, nullable=True)


class AlertRow(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    deal_id = Column(Integer, nullable=False, index=True)
    channels = Column(JSON, default=list)
    sent_at = Column(DateTime, default=datetime.utcnow)


def init_db(db_url: str = "sqlite:///listingiq.db") -> sessionmaker:
    """Initialize the database and return a session factory."""
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
