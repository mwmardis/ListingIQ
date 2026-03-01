"""Main deal analysis engine that orchestrates all analyzers."""

from __future__ import annotations

from listingiq.config import AnalysisConfig
from listingiq.models import Listing, DealAnalysis
from listingiq.analysis.brrr import BRRRAnalyzer
from listingiq.analysis.cashflow import CashFlowAnalyzer
from listingiq.analysis.flip import FlipAnalyzer


class DealAnalyzer:
    """Runs all configured analysis strategies against listings."""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self._analyzers: dict[str, BRRRAnalyzer | CashFlowAnalyzer | FlipAnalyzer] = {}

        if "brrr" in config.strategies:
            self._analyzers["brrr"] = BRRRAnalyzer(config.brrr, config.cash_flow)
        if "cash_flow" in config.strategies:
            self._analyzers["cash_flow"] = CashFlowAnalyzer(config.cash_flow)
        if "flip" in config.strategies:
            self._analyzers["flip"] = FlipAnalyzer(config.flip)

    def analyze_listing(
        self,
        listing: Listing,
        rent_estimate: float | None = None,
        arv_estimate: float | None = None,
    ) -> list[DealAnalysis]:
        """Analyze a single listing with all configured strategies.

        Args:
            listing: The property listing to analyze.
            rent_estimate: Optional comp-based monthly rent estimate.
            arv_estimate: Optional comp-based After Repair Value estimate.
        """
        results: list[DealAnalysis] = []
        for name, analyzer in self._analyzers.items():
            if isinstance(analyzer, BRRRAnalyzer):
                deal = analyzer.analyze(
                    listing, rent_estimate=rent_estimate, arv_estimate=arv_estimate
                )
            elif isinstance(analyzer, CashFlowAnalyzer):
                deal = analyzer.analyze(listing, rent_estimate=rent_estimate)
            elif isinstance(analyzer, FlipAnalyzer):
                deal = analyzer.analyze(listing, arv_estimate=arv_estimate)
            else:
                deal = analyzer.analyze(listing)
            results.append(deal)
        return results

    def analyze_listings(
        self,
        listings: list[Listing],
        rent_estimate: float | None = None,
        arv_estimate: float | None = None,
    ) -> list[DealAnalysis]:
        """Analyze multiple listings and return all deals that meet criteria."""
        all_deals: list[DealAnalysis] = []
        for listing in listings:
            deals = self.analyze_listing(
                listing, rent_estimate=rent_estimate, arv_estimate=arv_estimate
            )
            all_deals.extend(deals)
        return all_deals

    def get_top_deals(
        self,
        listings: list[Listing],
        min_score: float = 0,
        limit: int = 20,
        rent_estimate: float | None = None,
        arv_estimate: float | None = None,
    ) -> list[DealAnalysis]:
        """Analyze listings and return top deals sorted by score."""
        deals = self.analyze_listings(
            listings, rent_estimate=rent_estimate, arv_estimate=arv_estimate
        )
        qualified = [d for d in deals if d.score >= min_score and d.meets_criteria]
        qualified.sort(key=lambda d: d.score, reverse=True)
        return qualified[:limit]
