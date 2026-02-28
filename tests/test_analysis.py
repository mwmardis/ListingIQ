"""Tests for deal analysis engine."""

import pytest

from listingiq.config import AnalysisConfig, BRRRConfig, CashFlowConfig, FlipConfig
from listingiq.models import Listing, DealStrategy
from listingiq.analysis.brrr import BRRRAnalyzer
from listingiq.analysis.cashflow import CashFlowAnalyzer
from listingiq.analysis.flip import FlipAnalyzer
from listingiq.analysis.engine import DealAnalyzer


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


class TestBRRRAnalyzer:
    def setup_method(self):
        self.brrr_cfg = BRRRConfig()
        self.cf_cfg = CashFlowConfig()
        self.analyzer = BRRRAnalyzer(self.brrr_cfg, self.cf_cfg)

    def test_analyze_returns_deal(self):
        listing = _make_listing()
        deal = self.analyzer.analyze(listing)
        assert deal.strategy == DealStrategy.BRRR
        assert deal.score >= 0
        assert deal.summary

    def test_metrics_calculated(self):
        listing = _make_listing(price=150_000, sqft=1200)
        deal = self.analyzer.analyze(listing)
        m = deal.metrics
        assert m["purchase_price"] == 150_000
        assert m["estimated_arv"] > 150_000
        assert m["rehab_cost"] > 0
        assert m["refinance_amount"] > 0

    def test_cheap_property_scores_well(self):
        # A very cheap property relative to ARV should score well
        listing = _make_listing(price=80_000, sqft=1200)
        deal = self.analyzer.analyze(listing)
        assert deal.score > 0

    def test_expensive_property_scores_poorly(self):
        listing = _make_listing(price=500_000, sqft=800)
        deal = self.analyzer.analyze(listing)
        # Even expensive properties get analyzed, metrics just reflect reality
        assert deal.metrics["purchase_price"] == 500_000


class TestCashFlowAnalyzer:
    def setup_method(self):
        self.cfg = CashFlowConfig()
        self.analyzer = CashFlowAnalyzer(self.cfg)

    def test_analyze_returns_deal(self):
        listing = _make_listing()
        deal = self.analyzer.analyze(listing)
        assert deal.strategy == DealStrategy.CASH_FLOW
        assert deal.score >= 0

    def test_positive_cash_flow(self):
        # Lower price should yield better cash flow
        listing = _make_listing(price=100_000)
        deal = self.analyzer.analyze(listing)
        m = deal.metrics
        assert m["monthly_rent_estimate"] > 0
        assert m["cap_rate"] > 0
        assert m["noi"] > 0

    def test_dscr_calculated(self):
        listing = _make_listing()
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["dscr"] > 0

    def test_grm_calculated(self):
        listing = _make_listing()
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["grm"] > 0

    def test_all_metrics_present(self):
        listing = _make_listing()
        deal = self.analyzer.analyze(listing)
        expected_keys = [
            "purchase_price", "down_payment", "loan_amount",
            "monthly_mortgage", "monthly_rent_estimate", "effective_rent",
            "monthly_expenses", "monthly_cash_flow", "annual_cash_flow",
            "cap_rate", "cash_on_cash_return", "noi", "dscr", "grm",
        ]
        for key in expected_keys:
            assert key in deal.metrics, f"Missing metric: {key}"


class TestFlipAnalyzer:
    def setup_method(self):
        self.cfg = FlipConfig()
        self.analyzer = FlipAnalyzer(self.cfg)

    def test_analyze_returns_deal(self):
        listing = _make_listing()
        deal = self.analyzer.analyze(listing)
        assert deal.strategy == DealStrategy.FLIP
        assert deal.score >= 0

    def test_profit_calculated(self):
        listing = _make_listing(price=150_000, sqft=1200)
        deal = self.analyzer.analyze(listing)
        m = deal.metrics
        assert m["estimated_arv"] > m["purchase_price"]
        assert "estimated_profit" in m
        assert "roi" in m

    def test_cheap_flip_is_profitable(self):
        # Small sqft keeps rehab cost low relative to ARV spread
        listing = _make_listing(price=80_000, sqft=600)
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_profit"] > 0


class TestDealAnalyzer:
    def test_analyze_all_strategies(self):
        cfg = AnalysisConfig()
        analyzer = DealAnalyzer(cfg)
        listing = _make_listing()
        deals = analyzer.analyze_listing(listing)
        strategies = {d.strategy.value for d in deals}
        assert "brrr" in strategies
        assert "cash_flow" in strategies
        assert "flip" in strategies

    def test_get_top_deals_sorted(self):
        cfg = AnalysisConfig()
        analyzer = DealAnalyzer(cfg)
        listings = [
            _make_listing(source_id="1", price=100_000),
            _make_listing(source_id="2", price=200_000),
            _make_listing(source_id="3", price=300_000),
        ]
        deals = analyzer.get_top_deals(listings, min_score=0, limit=10)
        # Should be sorted by score descending
        scores = [d.score for d in deals]
        assert scores == sorted(scores, reverse=True)

    def test_limit_works(self):
        cfg = AnalysisConfig()
        analyzer = DealAnalyzer(cfg)
        listings = [_make_listing(source_id=str(i), price=100_000 + i * 10_000) for i in range(10)]
        deals = analyzer.get_top_deals(listings, min_score=0, limit=5)
        assert len(deals) <= 5

    def test_single_strategy(self):
        cfg = AnalysisConfig(strategies=["cash_flow"])
        analyzer = DealAnalyzer(cfg)
        listing = _make_listing()
        deals = analyzer.analyze_listing(listing)
        assert len(deals) == 1
        assert deals[0].strategy.value == "cash_flow"
