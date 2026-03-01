"""Data models for ListingIQ."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PropertyType(str, Enum):
    SINGLE_FAMILY = "single_family"
    MULTI_FAMILY = "multi_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"


class ListingStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SOLD = "sold"
    CONTINGENT = "contingent"


class DealStrategy(str, Enum):
    BRRR = "brrr"
    CASH_FLOW = "cash_flow"
    FLIP = "flip"


class Listing(BaseModel):
    """A property listing scraped from an MLS source."""

    source: str
    source_id: str
    url: str = ""
    address: str
    city: str
    state: str
    zip_code: str
    price: float
    beds: int = 0
    baths: float = 0
    sqft: int = 0
    lot_sqft: int = 0
    year_built: int = 0
    property_type: PropertyType = PropertyType.SINGLE_FAMILY
    status: ListingStatus = ListingStatus.ACTIVE
    days_on_market: int = 0
    hoa_monthly: float = 0.0
    tax_annual: float = 0.0
    description: str = ""
    images: list[str] = Field(default_factory=list)
    raw_data: dict = Field(default_factory=dict)
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def full_address(self) -> str:
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"

    @property
    def price_per_sqft(self) -> float:
        if self.sqft > 0:
            return self.price / self.sqft
        return 0.0


class DealAnalysis(BaseModel):
    """Results from analyzing a listing for investment potential."""

    listing: Listing
    strategy: DealStrategy
    score: float = 0.0  # 0-100
    metrics: dict = Field(default_factory=dict)
    meets_criteria: bool = False
    summary: str = ""
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class BRRRMetrics(BaseModel):
    """Metrics specific to BRRR analysis."""

    purchase_price: float
    estimated_arv: float
    rehab_cost: float
    total_investment: float
    holding_costs: float
    refinance_amount: float
    cash_left_in_deal: float
    monthly_rent_estimate: float
    monthly_expenses: float
    monthly_cash_flow: float
    annual_cash_flow: float
    cash_on_cash_return: float  # percentage
    equity_captured: float


class CashFlowMetrics(BaseModel):
    """Metrics specific to cash flow analysis."""

    purchase_price: float
    down_payment: float
    loan_amount: float
    monthly_mortgage: float
    monthly_rent_estimate: float
    effective_rent: float  # after vacancy
    monthly_expenses: float
    monthly_cash_flow: float
    annual_cash_flow: float
    cap_rate: float  # percentage
    cash_on_cash_return: float  # percentage
    noi: float
    dscr: float  # debt service coverage ratio
    grm: float  # gross rent multiplier


class FlipMetrics(BaseModel):
    """Metrics specific to flip analysis."""

    purchase_price: float
    estimated_arv: float
    rehab_cost: float
    holding_costs: float
    selling_costs: float
    total_cost: float
    estimated_profit: float
    roi: float  # percentage
    profit_per_month: float


class RentalComp(BaseModel):
    """A comparable rental listing used to estimate rent."""

    address: str
    monthly_rent: float
    beds: int
    baths: float
    sqft: int = 0
    distance_miles: float = 0.0
    source: str = ""


class SalesComp(BaseModel):
    """A comparable sold listing used to estimate ARV."""

    address: str
    sold_price: float
    sold_date: str = ""
    beds: int
    baths: float
    sqft: int = 0
    distance_miles: float = 0.0
    price_per_sqft: float = 0.0
    source: str = ""


class CompData(BaseModel):
    """Comparable data collected for a listing."""

    rental_comps: list[RentalComp] = Field(default_factory=list)
    sales_comps: list[SalesComp] = Field(default_factory=list)
    estimated_rent: Optional[float] = None
    estimated_arv: Optional[float] = None
    rent_confidence: str = "low"  # low, medium, high
    arv_confidence: str = "low"


class OfferResult(BaseModel):
    """Result of a reverse offer-price calculation."""

    strategy: DealStrategy
    target_metric: str
    target_value: float
    max_offer_price: float
    metrics_at_offer: dict = Field(default_factory=dict)
    discount_from_list: float = 0.0  # percentage below list price


class Alert(BaseModel):
    """An alert generated for a good deal."""

    deal: DealAnalysis
    channels_sent: list[str] = Field(default_factory=list)
    sent_at: Optional[datetime] = None
