"""Fix-and-flip deal analysis."""

from __future__ import annotations

from listingiq.config import FlipConfig
from listingiq.models import Listing, DealAnalysis, DealStrategy, FlipMetrics


class FlipAnalyzer:
    """Analyze listings for fix-and-flip potential.

    Evaluates whether buying, renovating, and reselling a property
    would yield a profitable return.
    """

    def __init__(self, config: FlipConfig):
        self.cfg = config

    def analyze(
        self,
        listing: Listing,
        arv_estimate: float | None = None,
    ) -> DealAnalysis:
        metrics = self._calculate_metrics(listing, arv_estimate=arv_estimate)
        score = self._score(metrics)
        meets = self._meets_criteria(metrics)

        return DealAnalysis(
            listing=listing,
            strategy=DealStrategy.FLIP,
            score=score,
            metrics=metrics.model_dump(),
            meets_criteria=meets,
            summary=self._summary(listing, metrics, score),
        )

    def _calculate_metrics(
        self,
        listing: Listing,
        arv_estimate: float | None = None,
    ) -> FlipMetrics:
        purchase_price = listing.price

        # Estimate ARV — use comp-based estimate if available
        if arv_estimate is not None:
            estimated_arv = arv_estimate
        else:
            estimated_arv = purchase_price / self.cfg.max_purchase_pct_of_arv

        # Rehab cost estimate based on difference between price and ARV
        # plus a baseline per-sqft cost
        rehab_per_sqft = 35.0  # reasonable default for flip-grade rehab
        rehab_cost = listing.sqft * rehab_per_sqft if listing.sqft else 30_000.0

        # Holding costs during project
        holding_costs = self.cfg.monthly_holding_cost * self.cfg.project_months

        # Selling costs (agent commissions, closing costs, etc.)
        selling_costs = estimated_arv * self.cfg.selling_cost_pct

        # Total cost
        total_cost = purchase_price + rehab_cost + holding_costs + selling_costs

        # Profit
        estimated_profit = estimated_arv - total_cost

        # ROI
        roi = (estimated_profit / (purchase_price + rehab_cost)) * 100 if (purchase_price + rehab_cost) > 0 else 0

        # Profit per month
        profit_per_month = estimated_profit / self.cfg.project_months if self.cfg.project_months > 0 else 0

        return FlipMetrics(
            purchase_price=purchase_price,
            estimated_arv=round(estimated_arv, 2),
            rehab_cost=round(rehab_cost, 2),
            holding_costs=round(holding_costs, 2),
            selling_costs=round(selling_costs, 2),
            total_cost=round(total_cost, 2),
            estimated_profit=round(estimated_profit, 2),
            roi=round(roi, 2),
            profit_per_month=round(profit_per_month, 2),
        )

    def _score(self, m: FlipMetrics) -> float:
        score = 0.0

        # Profit (up to 40 points)
        if m.estimated_profit >= 75_000:
            score += 40
        elif m.estimated_profit >= 50_000:
            score += 30
        elif m.estimated_profit >= 30_000:
            score += 20
        elif m.estimated_profit >= 15_000:
            score += 10

        # ROI (up to 30 points)
        if m.roi >= 30:
            score += 30
        elif m.roi >= 20:
            score += 22
        elif m.roi >= 15:
            score += 15
        elif m.roi >= 10:
            score += 8

        # Profit per month (up to 20 points) - measures time efficiency
        if m.profit_per_month >= 10_000:
            score += 20
        elif m.profit_per_month >= 7_000:
            score += 15
        elif m.profit_per_month >= 5_000:
            score += 10
        elif m.profit_per_month >= 3_000:
            score += 5

        # ARV spread bonus (up to 10 points)
        spread = m.estimated_arv - m.purchase_price
        if spread >= 100_000:
            score += 10
        elif spread >= 75_000:
            score += 7
        elif spread >= 50_000:
            score += 4

        return min(100, round(score, 1))

    def _meets_criteria(self, m: FlipMetrics) -> bool:
        return m.estimated_profit >= self.cfg.min_profit and m.roi > 0

    def _summary(self, listing: Listing, m: FlipMetrics, score: float) -> str:
        parts = [
            f"Flip Analysis for {listing.full_address}",
            f"Purchase: ${m.purchase_price:,.0f} | Est. ARV: ${m.estimated_arv:,.0f}",
            f"Rehab: ${m.rehab_cost:,.0f} | Holding: ${m.holding_costs:,.0f} | Selling: ${m.selling_costs:,.0f}",
            f"Total Cost: ${m.total_cost:,.0f} | Est. Profit: ${m.estimated_profit:,.0f}",
            f"ROI: {m.roi:.1f}% | Profit/Month: ${m.profit_per_month:,.0f}",
            f"Deal Score: {score}/100",
        ]
        return "\n".join(parts)
