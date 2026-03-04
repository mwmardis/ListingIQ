"""Tests for mortgage points calculator."""
import pytest
from listingiq.analysis.points import calculate_points_table


class TestPointsCalculator:
    def test_zero_points_baseline(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        assert len(result) > 0
        baseline = result[0]
        assert baseline["points"] == 0
        assert baseline["rate"] == 0.07
        assert baseline["point_cost"] == 0
        assert baseline["monthly_payment"] > 0

    def test_each_point_reduces_rate(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        rates = [r["rate"] for r in result]
        for i in range(1, len(rates)):
            assert rates[i] < rates[i - 1]

    def test_point_cost_is_correct(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        one_point = next(r for r in result if r["points"] == 1.0)
        # 1 point = 1% of loan amount
        assert one_point["point_cost"] == 2000

    def test_break_even_calculated(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        one_point = next(r for r in result if r["points"] == 1.0)
        assert one_point["break_even_months"] > 0

    def test_total_interest_decreases(self):
        result = calculate_points_table(
            loan_amount=200_000, base_rate=0.07, loan_term_years=30
        )
        interests = [r["total_interest"] for r in result]
        for i in range(1, len(interests)):
            assert interests[i] < interests[i - 1]
