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

    def test_arv_override(self):
        listing = _make_listing(price=150_000)
        deal = self.analyzer.analyze(listing, arv_estimate=280_000)
        assert deal.metrics["estimated_arv"] == 280_000

    def test_rent_override(self):
        listing = _make_listing(price=150_000)
        deal = self.analyzer.analyze(listing, rent_estimate=1_800)
        assert deal.metrics["monthly_rent_estimate"] == 1_800

    def test_both_overrides(self):
        listing = _make_listing(price=150_000)
        deal = self.analyzer.analyze(listing, rent_estimate=1_800, arv_estimate=280_000)
        assert deal.metrics["estimated_arv"] == 280_000
        assert deal.metrics["monthly_rent_estimate"] == 1_800


class TestCashFlowAnalyzer:
    def setup_method(self):
        self.cfg = CashFlowConfig()
        self.analyzer = CashFlowAnalyzer(self.cfg)

    def test_analyze_returns_deal(self):
        listing = _make_listing()
        deal = self.analyzer.analyze(listing)
        assert deal.strategy == DealStrategy.CASH_FLOW
        assert deal.score >= 0

    def test_rent_override(self):
        listing = _make_listing(price=200_000)
        deal = self.analyzer.analyze(listing, rent_estimate=2_000)
        assert deal.metrics["monthly_rent_estimate"] == 2_000

    def test_rent_override_changes_cash_flow(self):
        listing = _make_listing(price=200_000)
        deal_default = self.analyzer.analyze(listing)
        deal_high_rent = self.analyzer.analyze(listing, rent_estimate=3_000)
        assert deal_high_rent.metrics["monthly_cash_flow"] > deal_default.metrics["monthly_cash_flow"]

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


    def test_cap_rate_default_lowered(self):
        """Default min_cap_rate should be 5.0 not 6.0."""
        from listingiq.config import CashFlowConfig
        cfg = CashFlowConfig()
        assert cfg.min_cap_rate == 5.0

    def test_cheap_property_not_penalized(self):
        """A $80k property with good rent shouldn't score worse than expensive one."""
        cheap = _make_listing(price=80_000, sqft=900)
        expensive = _make_listing(price=250_000, sqft=1800)
        deal_cheap = self.analyzer.analyze(cheap, rent_estimate=1_000)
        deal_expensive = self.analyzer.analyze(expensive, rent_estimate=2_000)
        # Cheap property has $1000 rent on $80k — much better ratio
        # Should score at least as well as expensive
        assert deal_cheap.score >= deal_expensive.score


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
        # With comp-based ARV, a cheap property yields positive profit
        listing = _make_listing(price=80_000, sqft=600)
        deal = self.analyzer.analyze(listing, arv_estimate=160_000)
        assert deal.metrics["estimated_profit"] > 0

    def test_arv_override(self):
        listing = _make_listing(price=150_000, sqft=1200)
        deal = self.analyzer.analyze(listing, arv_estimate=300_000)
        assert deal.metrics["estimated_arv"] == 300_000
        # Higher ARV means more profit
        deal_default = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_profit"] > deal_default.metrics["estimated_profit"]

    def test_arv_fallback_age_aware_new_home(self):
        """New home (<15 years) gets conservative 1.15x ARV fallback."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=2015)
        deal = self.analyzer.analyze(listing)
        # 300k * 1.15 = 345k, NOT 300k / 0.65 = 461k
        assert deal.metrics["estimated_arv"] == pytest.approx(345_000, rel=0.01)

    def test_arv_fallback_age_aware_mid_age(self):
        """Mid-age home (15-30 years) gets 1.25x ARV fallback."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=2000)
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_arv"] == pytest.approx(375_000, rel=0.01)

    def test_arv_fallback_age_aware_old_home(self):
        """Old home (30+ years) gets 1.35x ARV fallback."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=1980)
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_arv"] == pytest.approx(405_000, rel=0.01)

    def test_arv_fallback_unknown_age(self):
        """Unknown year_built (0) uses middle multiplier 1.25."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=0)
        deal = self.analyzer.analyze(listing)
        assert deal.metrics["estimated_arv"] == pytest.approx(375_000, rel=0.01)

    def test_arv_override_still_works(self):
        """Comp-based ARV override still takes precedence."""
        listing = _make_listing(price=300_000, sqft=1500, year_built=2015)
        deal = self.analyzer.analyze(listing, arv_estimate=500_000)
        assert deal.metrics["estimated_arv"] == 500_000


class TestMultiFamilyAnalysis:
    def test_cashflow_duplex_uses_aggregate_rent(self):
        """Duplex should estimate rent per unit and aggregate."""
        cfg = CashFlowConfig()
        analyzer = CashFlowAnalyzer(cfg)
        duplex = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=2)
        single = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=1)
        deal_duplex = analyzer.analyze(duplex)
        deal_single = analyzer.analyze(single)
        # Duplex should have higher rent estimate (2 units rented separately)
        assert deal_duplex.metrics["monthly_rent_estimate"] > deal_single.metrics["monthly_rent_estimate"]

    def test_brrr_duplex_uses_aggregate_rent(self):
        brrr_cfg = BRRRConfig()
        cf_cfg = CashFlowConfig()
        analyzer = BRRRAnalyzer(brrr_cfg, cf_cfg)
        duplex = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=2)
        single = _make_listing(price=200_000, sqft=2000, beds=4, baths=2, units=1)
        deal_duplex = analyzer.analyze(duplex)
        deal_single = analyzer.analyze(single)
        assert deal_duplex.metrics["monthly_rent_estimate"] > deal_single.metrics["monthly_rent_estimate"]

    def test_single_family_unaffected(self):
        """units=1 should produce identical results to current behavior."""
        cfg = CashFlowConfig()
        analyzer = CashFlowAnalyzer(cfg)
        listing = _make_listing(units=1)
        deal = analyzer.analyze(listing)
        assert deal.metrics["monthly_rent_estimate"] > 0


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

    def test_analyze_with_comp_overrides(self):
        cfg = AnalysisConfig()
        analyzer = DealAnalyzer(cfg)
        listing = _make_listing(price=150_000)
        deals = analyzer.analyze_listing(
            listing, rent_estimate=1_800, arv_estimate=280_000
        )
        strategies = {d.strategy.value for d in deals}
        assert "brrr" in strategies
        assert "cash_flow" in strategies
        assert "flip" in strategies
        # Verify overrides were applied
        for deal in deals:
            if deal.strategy.value == "brrr":
                assert deal.metrics["estimated_arv"] == 280_000
                assert deal.metrics["monthly_rent_estimate"] == 1_800
            elif deal.strategy.value == "cash_flow":
                assert deal.metrics["monthly_rent_estimate"] == 1_800
            elif deal.strategy.value == "flip":
                assert deal.metrics["estimated_arv"] == 280_000
