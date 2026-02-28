"""BRRR (Buy, Rehab, Rent, Refinance, Repeat) deal analysis."""

from __future__ import annotations

from listingiq.config import BRRRConfig, CashFlowConfig
from listingiq.models import Listing, DealAnalysis, DealStrategy, BRRRMetrics


class BRRRAnalyzer:
    """Analyze listings for BRRR investment potential.

    The BRRR strategy involves buying a property below market value, rehabbing
    it to increase value, renting it out, then refinancing to pull out your
    initial investment and repeat with another property.
    """

    def __init__(self, brrr_config: BRRRConfig, cashflow_config: CashFlowConfig):
        self.cfg = brrr_config
        self.cf_cfg = cashflow_config

    def analyze(self, listing: Listing) -> DealAnalysis:
        """Run BRRR analysis on a listing."""
        metrics = self._calculate_metrics(listing)
        score = self._score(metrics)
        meets = self._meets_criteria(metrics)

        return DealAnalysis(
            listing=listing,
            strategy=DealStrategy.BRRR,
            score=score,
            metrics=metrics.model_dump(),
            meets_criteria=meets,
            summary=self._summary(listing, metrics, score),
        )

    def _calculate_metrics(self, listing: Listing) -> BRRRMetrics:
        purchase_price = listing.price

        # Estimate ARV: for properties needing rehab, ARV is typically
        # higher than purchase price. We use the purchase/ARV ratio from config.
        # If purchase is at max_purchase_pct_of_arv of ARV, then:
        # ARV = purchase_price / max_purchase_pct_of_arv
        estimated_arv = purchase_price / self.cfg.max_purchase_pct_of_arv

        # Rehab cost based on square footage
        rehab_cost = listing.sqft * self.cfg.rehab_cost_per_sqft if listing.sqft else 25_000.0

        # Holding costs during rehab
        holding_costs = self.cfg.monthly_holding_cost * self.cfg.rehab_months

        # Total cash invested
        total_investment = purchase_price + rehab_cost + holding_costs

        # Refinance: bank will lend LTV% of ARV
        refinance_amount = estimated_arv * self.cfg.refinance_ltv

        # Cash left in the deal after refinancing
        cash_left_in_deal = max(total_investment - refinance_amount, 0)

        # Rental income estimate
        monthly_rent = listing.price * self.cf_cfg.rent_estimate_pct
        # Use ARV-based rent for post-rehab
        monthly_rent_arv = estimated_arv * self.cf_cfg.rent_estimate_pct

        # Monthly expenses on the refinanced property
        monthly_mortgage = self._monthly_payment(
            refinance_amount, self.cf_cfg.interest_rate, self.cf_cfg.loan_term_years
        )
        monthly_tax = listing.tax_annual / 12 if listing.tax_annual else (estimated_arv * 0.012) / 12
        monthly_insurance = self.cf_cfg.annual_insurance / 12
        monthly_maintenance = (estimated_arv * self.cf_cfg.maintenance_pct) / 12
        monthly_management = monthly_rent_arv * self.cf_cfg.management_fee_pct
        vacancy_cost = monthly_rent_arv * self.cf_cfg.vacancy_rate
        monthly_hoa = listing.hoa_monthly

        monthly_expenses = (
            monthly_mortgage
            + monthly_tax
            + monthly_insurance
            + monthly_maintenance
            + monthly_management
            + vacancy_cost
            + monthly_hoa
        )

        monthly_cash_flow = monthly_rent_arv - monthly_expenses
        annual_cash_flow = monthly_cash_flow * 12

        # Cash-on-cash return based on cash left in deal
        cash_on_cash = 0.0
        if cash_left_in_deal > 0:
            cash_on_cash = (annual_cash_flow / cash_left_in_deal) * 100
        elif annual_cash_flow > 0:
            cash_on_cash = float("inf")  # infinite return if no cash left

        equity_captured = estimated_arv - refinance_amount

        return BRRRMetrics(
            purchase_price=purchase_price,
            estimated_arv=round(estimated_arv, 2),
            rehab_cost=round(rehab_cost, 2),
            total_investment=round(total_investment, 2),
            holding_costs=round(holding_costs, 2),
            refinance_amount=round(refinance_amount, 2),
            cash_left_in_deal=round(cash_left_in_deal, 2),
            monthly_rent_estimate=round(monthly_rent_arv, 2),
            monthly_expenses=round(monthly_expenses, 2),
            monthly_cash_flow=round(monthly_cash_flow, 2),
            annual_cash_flow=round(annual_cash_flow, 2),
            cash_on_cash_return=round(cash_on_cash, 2),
            equity_captured=round(equity_captured, 2),
        )

    def _monthly_payment(self, principal: float, annual_rate: float, years: int) -> float:
        """Calculate monthly mortgage payment."""
        if principal <= 0 or annual_rate <= 0:
            return 0.0
        monthly_rate = annual_rate / 12
        num_payments = years * 12
        payment = principal * (monthly_rate * (1 + monthly_rate) ** num_payments) / (
            (1 + monthly_rate) ** num_payments - 1
        )
        return payment

    def _score(self, m: BRRRMetrics) -> float:
        """Score the deal 0-100."""
        score = 0.0

        # Cash-on-cash return (up to 40 points)
        if m.cash_on_cash_return >= 25:
            score += 40
        elif m.cash_on_cash_return >= 15:
            score += 30
        elif m.cash_on_cash_return >= 10:
            score += 20
        elif m.cash_on_cash_return >= 5:
            score += 10

        # Cash left in deal (up to 25 points) - less is better
        investment_recovery = 1 - (m.cash_left_in_deal / m.total_investment) if m.total_investment else 0
        score += max(0, min(25, investment_recovery * 25))

        # Monthly cash flow (up to 20 points)
        if m.monthly_cash_flow >= 500:
            score += 20
        elif m.monthly_cash_flow >= 300:
            score += 15
        elif m.monthly_cash_flow >= 200:
            score += 10
        elif m.monthly_cash_flow >= 100:
            score += 5

        # Equity captured (up to 15 points)
        if m.equity_captured >= 50_000:
            score += 15
        elif m.equity_captured >= 30_000:
            score += 10
        elif m.equity_captured >= 15_000:
            score += 5

        return min(100, round(score, 1))

    def _meets_criteria(self, m: BRRRMetrics) -> bool:
        """Check if the deal meets minimum BRRR criteria."""
        return (
            m.cash_on_cash_return >= self.cfg.min_cash_on_cash_return
            and m.monthly_cash_flow > 0
        )

    def _summary(self, listing: Listing, m: BRRRMetrics, score: float) -> str:
        parts = [
            f"BRRR Analysis for {listing.full_address}",
            f"Purchase: ${m.purchase_price:,.0f} | Est. ARV: ${m.estimated_arv:,.0f}",
            f"Rehab: ${m.rehab_cost:,.0f} | Total Investment: ${m.total_investment:,.0f}",
            f"Refinance: ${m.refinance_amount:,.0f} | Cash Left: ${m.cash_left_in_deal:,.0f}",
            f"Monthly Cash Flow: ${m.monthly_cash_flow:,.0f} | CoC Return: {m.cash_on_cash_return:.1f}%",
            f"Deal Score: {score}/100",
        ]
        return "\n".join(parts)
