"""Mortgage points calculator -- shows cost/benefit of buying down the rate."""

from __future__ import annotations


def _monthly_payment(principal: float, annual_rate: float, years: int) -> float:
    if principal <= 0 or annual_rate <= 0:
        return 0.0
    monthly_rate = annual_rate / 12
    n = years * 12
    return principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)


def calculate_points_table(
    loan_amount: float,
    base_rate: float,
    loan_term_years: int = 30,
    max_points: float = 3.0,
    step: float = 0.25,
) -> list[dict]:
    """Generate a comparison table for 0 to max_points.

    Each point costs 1% of the loan amount and reduces the rate by 0.25%.

    Returns list of dicts with: points, rate, monthly_payment, total_interest,
    break_even_months, point_cost.
    """
    baseline_payment = _monthly_payment(loan_amount, base_rate, loan_term_years)
    total_payments = loan_term_years * 12
    results: list[dict] = []

    points = 0.0
    while points <= max_points + 0.001:
        rate = base_rate - (points * 0.0025)  # 0.25% per point
        payment = _monthly_payment(loan_amount, rate, loan_term_years)
        total_interest = (payment * total_payments) - loan_amount
        point_cost = loan_amount * (points / 100)
        monthly_savings = baseline_payment - payment

        if monthly_savings > 0 and points > 0:
            break_even = round(point_cost / monthly_savings)
        else:
            break_even = 0

        results.append({
            "points": round(points, 2),
            "rate": round(rate, 4),
            "monthly_payment": round(payment, 2),
            "total_interest": round(total_interest, 2),
            "break_even_months": break_even,
            "point_cost": round(point_cost, 2),
        })

        points += step

    return results
