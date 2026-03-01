"""Offer price calculator — reverse-engineers the max offer price from a target return.

For each strategy, works backwards from the investor's target metric to
determine the highest price they should pay for the property.
"""

from __future__ import annotations

from listingiq.config import AnalysisConfig
from listingiq.models import (
    Listing,
    DealStrategy,
    OfferResult,
)
from listingiq.analysis.brrr import BRRRAnalyzer
from listingiq.analysis.cashflow import CashFlowAnalyzer
from listingiq.analysis.flip import FlipAnalyzer


class OfferCalculator:
    """Calculates the maximum offer price to achieve a target return."""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.offer_cfg = config.offer
        self._brrr = BRRRAnalyzer(config.brrr, config.cash_flow)
        self._cashflow = CashFlowAnalyzer(config.cash_flow)
        self._flip = FlipAnalyzer(config.flip)

    def calculate_offer_price(
        self,
        listing: Listing,
        strategy: str | DealStrategy,
        target_metric: str | None = None,
        target_value: float | None = None,
        rent_estimate: float | None = None,
        arv_estimate: float | None = None,
    ) -> OfferResult:
        """Calculate the max offer price for a listing given a target return.

        Args:
            listing: The property listing (price is used as the starting point).
            strategy: Which strategy to optimize for.
            target_metric: The metric to target (e.g., "monthly_cash_flow", "cash_on_cash_return").
            target_value: The desired value for that metric.
            rent_estimate: Optional comp-based rent estimate.
            arv_estimate: Optional comp-based ARV estimate.

        Returns:
            OfferResult with the max offer price and metrics at that price.
        """
        if isinstance(strategy, str):
            strategy = DealStrategy(strategy)

        if strategy == DealStrategy.CASH_FLOW:
            return self._calc_cashflow_offer(
                listing, target_metric, target_value, rent_estimate
            )
        elif strategy == DealStrategy.BRRR:
            return self._calc_brrr_offer(
                listing, target_metric, target_value, rent_estimate, arv_estimate
            )
        elif strategy == DealStrategy.FLIP:
            return self._calc_flip_offer(
                listing, target_metric, target_value, arv_estimate
            )
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

    def calculate_all_offers(
        self,
        listing: Listing,
        rent_estimate: float | None = None,
        arv_estimate: float | None = None,
    ) -> list[OfferResult]:
        """Calculate offer prices for all configured strategies."""
        results: list[OfferResult] = []
        for strategy_name in self.config.strategies:
            try:
                result = self.calculate_offer_price(
                    listing,
                    strategy=strategy_name,
                    rent_estimate=rent_estimate,
                    arv_estimate=arv_estimate,
                )
                results.append(result)
            except Exception:
                continue
        return results

    def _calc_cashflow_offer(
        self,
        listing: Listing,
        target_metric: str | None,
        target_value: float | None,
        rent_estimate: float | None,
    ) -> OfferResult:
        """Binary search for the max price yielding target cash flow."""
        metric = target_metric or "monthly_cash_flow"
        if metric == "monthly_cash_flow":
            target = target_value if target_value is not None else self.offer_cfg.cash_flow_target_monthly
        else:
            target = target_value if target_value is not None else self.offer_cfg.cash_flow_target_coc

        # Binary search: the max price where metric >= target
        low = 1_000.0
        high = listing.price * 1.5  # search up to 150% of list price
        best_price = low

        for _ in range(self.offer_cfg.max_iterations):
            if high - low < self.offer_cfg.price_tolerance:
                break

            mid = (low + high) / 2
            test_listing = listing.model_copy(update={"price": mid})
            deal = self._cashflow.analyze(test_listing, rent_estimate=rent_estimate)

            current_value = deal.metrics.get(metric, 0)
            if current_value >= target:
                best_price = mid
                low = mid  # can afford to pay more
            else:
                high = mid  # need to pay less

        # Get final metrics at the best price
        final_listing = listing.model_copy(update={"price": best_price})
        final_deal = self._cashflow.analyze(final_listing, rent_estimate=rent_estimate)

        discount = ((listing.price - best_price) / listing.price) * 100 if listing.price > 0 else 0

        return OfferResult(
            strategy=DealStrategy.CASH_FLOW,
            target_metric=metric,
            target_value=target,
            max_offer_price=round(best_price, 0),
            metrics_at_offer=final_deal.metrics,
            discount_from_list=round(discount, 1),
        )

    def _calc_brrr_offer(
        self,
        listing: Listing,
        target_metric: str | None,
        target_value: float | None,
        rent_estimate: float | None,
        arv_estimate: float | None,
    ) -> OfferResult:
        """Binary search for the max price yielding target BRRR return."""
        metric = target_metric or "cash_on_cash_return"
        target = target_value if target_value is not None else self.offer_cfg.brrr_target_coc

        low = 1_000.0
        high = listing.price * 1.5
        best_price = low

        for _ in range(self.offer_cfg.max_iterations):
            if high - low < self.offer_cfg.price_tolerance:
                break

            mid = (low + high) / 2
            test_listing = listing.model_copy(update={"price": mid})
            deal = self._brrr.analyze(
                test_listing, rent_estimate=rent_estimate, arv_estimate=arv_estimate
            )

            current_value = deal.metrics.get(metric, 0)
            if current_value >= target:
                best_price = mid
                low = mid
            else:
                high = mid

        final_listing = listing.model_copy(update={"price": best_price})
        final_deal = self._brrr.analyze(
            final_listing, rent_estimate=rent_estimate, arv_estimate=arv_estimate
        )

        discount = ((listing.price - best_price) / listing.price) * 100 if listing.price > 0 else 0

        return OfferResult(
            strategy=DealStrategy.BRRR,
            target_metric=metric,
            target_value=target,
            max_offer_price=round(best_price, 0),
            metrics_at_offer=final_deal.metrics,
            discount_from_list=round(discount, 1),
        )

    def _calc_flip_offer(
        self,
        listing: Listing,
        target_metric: str | None,
        target_value: float | None,
        arv_estimate: float | None,
    ) -> OfferResult:
        """Direct calculation for flip — solve for max purchase price.

        profit = ARV - purchase - rehab - holding - selling
        purchase = ARV - rehab - holding - selling - target_profit
        """
        metric = target_metric or "estimated_profit"
        target_profit = target_value if target_value is not None else self.offer_cfg.flip_target_profit

        # Get ARV estimate
        if arv_estimate:
            estimated_arv = arv_estimate
        else:
            estimated_arv = listing.price / self.config.flip.max_purchase_pct_of_arv

        # Calculate costs
        rehab_per_sqft = 35.0
        rehab_cost = listing.sqft * rehab_per_sqft if listing.sqft else 30_000.0
        holding_costs = self.config.flip.monthly_holding_cost * self.config.flip.project_months
        selling_costs = estimated_arv * self.config.flip.selling_cost_pct

        # Solve directly: max_purchase = ARV - rehab - holding - selling - target_profit
        max_offer = estimated_arv - rehab_cost - holding_costs - selling_costs - target_profit
        max_offer = max(max_offer, 0)

        # Get metrics at this price
        final_listing = listing.model_copy(update={"price": max_offer})
        final_deal = self._flip.analyze(final_listing, arv_estimate=arv_estimate)

        discount = ((listing.price - max_offer) / listing.price) * 100 if listing.price > 0 else 0

        return OfferResult(
            strategy=DealStrategy.FLIP,
            target_metric=metric,
            target_value=target_profit,
            max_offer_price=round(max_offer, 0),
            metrics_at_offer=final_deal.metrics,
            discount_from_list=round(discount, 1),
        )
