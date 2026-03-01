"""Configuration management for ListingIQ."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

CONFIG_DIR = Path(__file__).parent.parent / "config"


class SearchConfig(BaseModel):
    markets: list[str] = ["Austin, TX"]
    property_types: list[str] = ["single_family", "multi_family"]
    min_price: int = 50_000
    max_price: int = 500_000
    min_beds: int = 2
    max_beds: int = 6
    min_baths: int = 1
    max_baths: int = 4


class ScraperConfig(BaseModel):
    sources: list[str] = ["redfin"]
    interval_minutes: int = 60
    max_concurrency: int = 5
    delay_min: float = 1.0
    delay_max: float = 3.0
    search: SearchConfig = SearchConfig()


class BRRRConfig(BaseModel):
    max_purchase_pct_of_arv: float = 0.70
    rehab_cost_per_sqft: float = 30.0
    refinance_ltv: float = 0.75
    min_cash_on_cash_return: float = 8.0
    monthly_holding_cost: float = 1500.0
    rehab_months: int = 4


class CashFlowConfig(BaseModel):
    down_payment_pct: float = 0.20
    interest_rate: float = 0.07
    loan_term_years: int = 30
    rent_estimate_pct: float = 0.008
    vacancy_rate: float = 0.05
    management_fee_pct: float = 0.10
    maintenance_pct: float = 0.01
    annual_insurance: float = 1800.0
    min_monthly_cash_flow: float = 200.0
    min_cap_rate: float = 6.0


class FlipConfig(BaseModel):
    max_purchase_pct_of_arv: float = 0.65
    min_profit: float = 30_000.0
    selling_cost_pct: float = 0.08
    monthly_holding_cost: float = 2000.0
    project_months: int = 6


class CompsConfig(BaseModel):
    enabled: bool = True
    # Sales comps settings
    sales_radius_miles: float = 0.5
    sales_max_age_days: int = 180
    sales_max_comps: int = 10
    sales_sqft_tolerance: float = 0.20  # ±20% of subject sqft
    sales_beds_tolerance: int = 1  # ±1 bedroom
    # Rental comps settings
    rental_radius_miles: float = 1.0
    rental_max_comps: int = 10
    rental_beds_tolerance: int = 0  # exact match preferred for rent
    # Confidence thresholds
    min_comps_for_high_confidence: int = 5
    min_comps_for_medium_confidence: int = 3
    # Fallback rent estimation factors (used when no comps found)
    # Rent per sqft by property type (monthly $/sqft)
    rent_per_sqft_single_family: float = 1.10
    rent_per_sqft_multi_family: float = 1.00
    rent_per_sqft_condo: float = 1.20
    rent_per_sqft_townhouse: float = 1.15


class OfferConfig(BaseModel):
    # Default target returns for each strategy
    cash_flow_target_monthly: float = 200.0
    cash_flow_target_coc: float = 8.0
    brrr_target_coc: float = 10.0
    flip_target_profit: float = 30_000.0
    # Binary search parameters
    max_iterations: int = 50
    price_tolerance: float = 500.0  # stop when within $500


class AnalysisConfig(BaseModel):
    strategies: list[str] = ["brrr", "cash_flow", "flip"]
    brrr: BRRRConfig = BRRRConfig()
    cash_flow: CashFlowConfig = CashFlowConfig()
    flip: FlipConfig = FlipConfig()
    comps: CompsConfig = CompsConfig()
    offer: OfferConfig = OfferConfig()


class EmailConfig(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = ""
    to_addresses: list[str] = []


class SMSConfig(BaseModel):
    account_sid: str = ""
    auth_token: str = ""
    from_number: str = ""
    to_numbers: list[str] = []


class WebhookConfig(BaseModel):
    urls: list[str] = []


class AlertsConfig(BaseModel):
    channels: list[str] = ["console"]
    min_deal_score: int = 70
    email: EmailConfig = EmailConfig()
    sms: SMSConfig = SMSConfig()
    webhook: WebhookConfig = WebhookConfig()


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///listingiq.db"


class AppConfig(BaseModel):
    scraper: ScraperConfig = ScraperConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    alerts: AlertsConfig = AlertsConfig()
    database: DatabaseConfig = DatabaseConfig()


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from TOML files.

    Loads default.toml first, then merges local.toml or a custom path on top.
    """
    default_path = CONFIG_DIR / "default.toml"
    data: dict[str, Any] = {}

    if default_path.exists():
        with open(default_path, "rb") as f:
            data = tomllib.load(f)

    local_path = config_path or CONFIG_DIR / "local.toml"
    if local_path.exists():
        with open(local_path, "rb") as f:
            overrides = tomllib.load(f)
        data = _deep_merge(data, overrides)

    return AppConfig(**data)
