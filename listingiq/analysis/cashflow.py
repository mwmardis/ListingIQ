"""Cash flow deal analysis for buy-and-hold rental strategy."""

from __future__ import annotations

from listingiq.config import CashFlowConfig
from listingiq.models import Listing, DealAnalysis, DealStrategy, CashFlowMetrics


class CashFlowAnalyzer:
    """Analyze listings for cash flow rental investment potential.

    Evaluates whether a property will generate positive monthly cash flow
    as a rental, accounting for mortgage, taxes, insurance, maintenance,
    vacancy, and management costs.
    """

    def __init__(self, config: CashFlowConfig):
        self.cfg = config

    def analyze(
        self,
        listing: Listing,
        rent_estimate: float | None = None,
    ) -> DealAnalysis:
        metrics = self._calculate_metrics(listing, rent_estimate=rent_estimate)
        score = self._score(metrics)
        meets = self._meets_criteria(metrics)

        return DealAnalysis(
            listing=listing,
            strategy=DealStrategy.CASH_FLOW,
            score=score,
            metrics=metrics.model_dump(),
            meets_criteria=meets,
            summary=self._summary(listing, metrics, score),
        )

    def _calculate_metrics(
        self,
        listing: Listing,
        rent_estimate: float | None = None,
    ) -> CashFlowMetrics:
        purchase_price = listing.price

        # Financing
        down_payment = purchase_price * self.cfg.down_payment_pct
        loan_amount = purchase_price - down_payment
        monthly_mortgage = self._monthly_payment(
            loan_amount, self.cfg.interest_rate, self.cfg.loan_term_years
        )

        # Income — use comp-based rent if available, otherwise fall back to percentage
        if rent_estimate is not None:
            monthly_rent = rent_estimate
        else:
            monthly_rent = purchase_price * self.cfg.rent_estimate_pct
        effective_rent = monthly_rent * (1 - self.cfg.vacancy_rate)

        # Expenses
        monthly_tax = listing.tax_annual / 12 if listing.tax_annual else (purchase_price * 0.012) / 12
        monthly_insurance = self.cfg.annual_insurance / 12
        monthly_maintenance = (purchase_price * self.cfg.maintenance_pct) / 12
        monthly_management = monthly_rent * self.cfg.management_fee_pct
        monthly_hoa = listing.hoa_monthly

        total_monthly_expenses = (
            monthly_mortgage
            + monthly_tax
            + monthly_insurance
            + monthly_maintenance
            + monthly_management
            + monthly_hoa
        )

        # Cash flow
        monthly_cash_flow = effective_rent - total_monthly_expenses
        annual_cash_flow = monthly_cash_flow * 12

        # NOI (Net Operating Income) - before debt service
        annual_gross_income = monthly_rent * 12
        annual_vacancy_loss = annual_gross_income * self.cfg.vacancy_rate
        annual_operating_expenses = (
            (monthly_tax + monthly_insurance + monthly_maintenance + monthly_management + monthly_hoa) * 12
        )
        noi = annual_gross_income - annual_vacancy_loss - annual_operating_expenses

        # Cap rate
        cap_rate = (noi / purchase_price) * 100 if purchase_price > 0 else 0

        # Cash-on-cash return
        total_cash_invested = down_payment  # simplified; could include closing costs
        cash_on_cash = (annual_cash_flow / total_cash_invested) * 100 if total_cash_invested > 0 else 0

        # DSCR (Debt Service Coverage Ratio)
        annual_debt_service = monthly_mortgage * 12
        dscr = noi / annual_debt_service if annual_debt_service > 0 else float("inf")

        # GRM (Gross Rent Multiplier)
        annual_rent = monthly_rent * 12
        grm = purchase_price / annual_rent if annual_rent > 0 else float("inf")

        return CashFlowMetrics(
            purchase_price=purchase_price,
            down_payment=round(down_payment, 2),
            loan_amount=round(loan_amount, 2),
            monthly_mortgage=round(monthly_mortgage, 2),
            monthly_rent_estimate=round(monthly_rent, 2),
            effective_rent=round(effective_rent, 2),
            monthly_expenses=round(total_monthly_expenses, 2),
            monthly_cash_flow=round(monthly_cash_flow, 2),
            annual_cash_flow=round(annual_cash_flow, 2),
            cap_rate=round(cap_rate, 2),
            cash_on_cash_return=round(cash_on_cash, 2),
            noi=round(noi, 2),
            dscr=round(dscr, 2),
            grm=round(grm, 2),
        )

    def _monthly_payment(self, principal: float, annual_rate: float, years: int) -> float:
        if principal <= 0 or annual_rate <= 0:
            return 0.0
        monthly_rate = annual_rate / 12
        num_payments = years * 12
        payment = principal * (monthly_rate * (1 + monthly_rate) ** num_payments) / (
            (1 + monthly_rate) ** num_payments - 1
        )
        return payment

    def _score(self, m: CashFlowMetrics) -> float:
        score = 0.0

        # Monthly cash flow (up to 35 points)
        if m.monthly_cash_flow >= 500:
            score += 35
        elif m.monthly_cash_flow >= 300:
            score += 25
        elif m.monthly_cash_flow >= 200:
            score += 18
        elif m.monthly_cash_flow >= 100:
            score += 10
        elif m.monthly_cash_flow > 0:
            score += 5

        # Cap rate (up to 25 points)
        if m.cap_rate >= 10:
            score += 25
        elif m.cap_rate >= 8:
            score += 20
        elif m.cap_rate >= 6:
            score += 15
        elif m.cap_rate >= 4:
            score += 8

        # Cash-on-cash return (up to 20 points)
        if m.cash_on_cash_return >= 15:
            score += 20
        elif m.cash_on_cash_return >= 10:
            score += 15
        elif m.cash_on_cash_return >= 8:
            score += 10
        elif m.cash_on_cash_return >= 5:
            score += 5

        # DSCR (up to 10 points) - higher is safer
        if m.dscr >= 1.5:
            score += 10
        elif m.dscr >= 1.25:
            score += 7
        elif m.dscr >= 1.0:
            score += 3

        # GRM bonus (up to 10 points) - lower is better
        if m.grm <= 8:
            score += 10
        elif m.grm <= 10:
            score += 7
        elif m.grm <= 12:
            score += 4

        return min(100, round(score, 1))

    def _meets_criteria(self, m: CashFlowMetrics) -> bool:
        return (
            m.monthly_cash_flow >= self.cfg.min_monthly_cash_flow
            and m.cap_rate >= self.cfg.min_cap_rate
        )

    def _summary(self, listing: Listing, m: CashFlowMetrics, score: float) -> str:
        parts = [
            f"Cash Flow Analysis for {listing.full_address}",
            f"Purchase: ${m.purchase_price:,.0f} | Down Payment: ${m.down_payment:,.0f}",
            f"Monthly Rent: ${m.monthly_rent_estimate:,.0f} | Mortgage: ${m.monthly_mortgage:,.0f}",
            f"Monthly Cash Flow: ${m.monthly_cash_flow:,.0f} | Annual: ${m.annual_cash_flow:,.0f}",
            f"Cap Rate: {m.cap_rate:.1f}% | CoC Return: {m.cash_on_cash_return:.1f}% | DSCR: {m.dscr:.2f}",
            f"Deal Score: {score}/100",
        ]
        return "\n".join(parts)
