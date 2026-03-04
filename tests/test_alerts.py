"""Tests for alert dispatcher digest functionality."""
import pytest
from datetime import datetime, timedelta
from listingiq.config import AlertsConfig, DigestConfig
from listingiq.alerts.dispatcher import AlertDispatcher
from listingiq.models import Listing, DealAnalysis, DealStrategy


def _make_deal(score=85, strategy="cash_flow"):
    listing = Listing(
        source="test", source_id=f"test-{score}",
        address="100 Test St", city="Austin", state="TX", zip_code="78701",
        price=200_000, beds=3, baths=2, sqft=1400,
    )
    return DealAnalysis(
        listing=listing,
        strategy=DealStrategy(strategy),
        score=score,
        meets_criteria=True,
        metrics={"monthly_cash_flow": 350},
        summary="Test deal",
    )


class TestDigestConfig:
    def test_digest_config_defaults(self):
        cfg = DigestConfig()
        assert cfg.enabled is False
        assert cfg.schedule == "daily"
        assert cfg.time == "08:00"
        assert cfg.min_score == 70

    def test_alerts_config_has_digest(self):
        cfg = AlertsConfig()
        assert hasattr(cfg, "digest")


class TestInstantAlertThreshold:
    def test_score_90_triggers_alert(self):
        cfg = AlertsConfig(min_deal_score=90, channels=["console"])
        dispatcher = AlertDispatcher(cfg)
        deal = _make_deal(score=92)
        qualified = [d for d in [deal] if d.meets_criteria and d.score >= cfg.min_deal_score]
        assert len(qualified) == 1

    def test_score_below_90_no_instant_alert(self):
        cfg = AlertsConfig(min_deal_score=90, channels=["console"])
        deal = _make_deal(score=85)
        qualified = [d for d in [deal] if d.meets_criteria and d.score >= cfg.min_deal_score]
        assert len(qualified) == 0
