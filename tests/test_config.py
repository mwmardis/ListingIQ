"""Tests for configuration loading."""

from pathlib import Path

from listingiq.config import load_config, AppConfig


def test_load_default_config():
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert len(cfg.scraper.sources) > 0
    assert len(cfg.analysis.strategies) > 0


def test_config_has_all_sections():
    cfg = load_config()
    assert cfg.scraper.search.min_price >= 0
    assert cfg.scraper.search.max_price > cfg.scraper.search.min_price
    assert cfg.analysis.brrr.max_purchase_pct_of_arv > 0
    assert cfg.analysis.cash_flow.interest_rate > 0
    assert cfg.analysis.flip.min_profit > 0
    assert cfg.alerts.min_deal_score >= 0
    assert cfg.database.url


def test_config_deep_merge():
    from listingiq.config import _deep_merge

    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"b": 10}, "e": 5}
    result = _deep_merge(base, override)
    assert result == {"a": {"b": 10, "c": 2}, "d": 3, "e": 5}
