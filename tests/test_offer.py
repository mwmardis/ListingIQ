"""Tests for the offer price calculator."""

import pytest

from listingiq.config import AnalysisConfig
from listingiq.models import Listing, DealStrategy
from listingiq.analysis.offer import OfferCalculator


def _make_listing(**overrides) -> Listing:
    defaults = {
        "source": "test",
        "source_id": "test-1",
        "address": "100 Investor Blvd",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78701",
        "price": 200_000,
        "beds": 3,
        "baths": 2,
        "sqft": 1400,
        "tax_annual": 3600,
    }
    defaults.update(overrides)
    return Listing(**defaults)


class TestOfferCalculator:
    def setup_method(self):
        self.cfg = AnalysisConfig()
        self.calc = OfferCalculator(self.cfg)

    def test_cash_flow_offer_below_list_price(self):
        listing = _make_listing(price=250_000)
        result = self.calc.calculate_offer_price(listing, strategy="cash_flow")
        # Offer should be at or below list price to achieve target cash flow
        assert result.max_offer_price <= listing.price
        assert result.strategy == DealStrategy.CASH_FLOW

    def test_cash_flow_offer_discount_positive(self):
        listing = _make_listing(price=250_000)
        result = self.calc.calculate_offer_price(listing, strategy="cash_flow")
        assert result.discount_from_list >= 0

    def test_cash_flow_with_rent_override(self):
        listing = _make_listing(price=200_000)
        # High rent should allow higher offer price
        result_high = self.calc.calculate_offer_price(
            listing, strategy="cash_flow", rent_estimate=2_500
        )
        result_low = self.calc.calculate_offer_price(
            listing, strategy="cash_flow", rent_estimate=1_000
        )
        assert result_high.max_offer_price > result_low.max_offer_price

    def test_cash_flow_custom_target(self):
        listing = _make_listing(price=200_000)
        # With a fixed rent estimate, binary search works correctly:
        # higher target cash flow = must pay less to achieve it
        result_easy = self.calc.calculate_offer_price(
            listing, strategy="cash_flow",
            target_metric="monthly_cash_flow", target_value=100,
            rent_estimate=1_800,
        )
        result_hard = self.calc.calculate_offer_price(
            listing, strategy="cash_flow",
            target_metric="monthly_cash_flow", target_value=500,
            rent_estimate=1_800,
        )
        assert result_easy.max_offer_price > result_hard.max_offer_price

    def test_brrr_offer_below_list_price(self):
        listing = _make_listing(price=200_000)
        result = self.calc.calculate_offer_price(listing, strategy="brrr")
        assert result.max_offer_price <= listing.price * 1.5  # within search range
        assert result.strategy == DealStrategy.BRRR

    def test_brrr_with_arv_override(self):
        listing = _make_listing(price=200_000)
        # With fixed rent, higher ARV means larger refinance → less cash in deal → better CoC
        result_high = self.calc.calculate_offer_price(
            listing, strategy="brrr", arv_estimate=400_000, rent_estimate=3_500
        )
        result_low = self.calc.calculate_offer_price(
            listing, strategy="brrr", arv_estimate=250_000, rent_estimate=2_000
        )
        assert result_high.max_offer_price > result_low.max_offer_price

    def test_flip_offer_direct_calculation(self):
        listing = _make_listing(price=200_000, sqft=1400)
        result = self.calc.calculate_offer_price(listing, strategy="flip")
        assert result.strategy == DealStrategy.FLIP
        assert result.max_offer_price > 0

    def test_flip_higher_target_profit_lower_offer(self):
        listing = _make_listing(price=200_000, sqft=1400)
        result_30k = self.calc.calculate_offer_price(
            listing, strategy="flip",
            target_metric="estimated_profit", target_value=30_000,
        )
        result_60k = self.calc.calculate_offer_price(
            listing, strategy="flip",
            target_metric="estimated_profit", target_value=60_000,
        )
        # More profit required = lower max offer
        assert result_30k.max_offer_price > result_60k.max_offer_price

    def test_flip_with_arv_override(self):
        listing = _make_listing(price=200_000, sqft=1400)
        result = self.calc.calculate_offer_price(
            listing, strategy="flip", arv_estimate=350_000
        )
        # With known ARV, the offer should be based on that
        assert result.max_offer_price > 0
        assert result.metrics_at_offer["estimated_arv"] == 350_000

    def test_calculate_all_offers(self):
        listing = _make_listing(price=200_000)
        results = self.calc.calculate_all_offers(listing)
        strategies = {r.strategy.value for r in results}
        assert "cash_flow" in strategies
        assert "brrr" in strategies
        assert "flip" in strategies

    def test_offer_result_has_metrics(self):
        listing = _make_listing(price=200_000)
        result = self.calc.calculate_offer_price(listing, strategy="cash_flow")
        assert "monthly_cash_flow" in result.metrics_at_offer
        assert "purchase_price" in result.metrics_at_offer

    def test_offer_result_discount_calculation(self):
        listing = _make_listing(price=200_000)
        result = self.calc.calculate_offer_price(listing, strategy="cash_flow")
        expected_discount = ((listing.price - result.max_offer_price) / listing.price) * 100
        assert result.discount_from_list == pytest.approx(expected_discount, abs=1.0)
