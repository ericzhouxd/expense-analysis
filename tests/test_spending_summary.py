from dataclasses import replace
from datetime import date

from expense_analysis.spending_plan import Commitment, SpendingPlan
from expense_analysis.spending_summary import previous_year, spending_summary


def row(identifier, day, amount, category="Food", kind="expense"):
    return dict(
        id=identifier,
        transaction_date=day,
        amount_cents=amount,
        category=category,
        transaction_type=kind,
    )


def plan():
    return SpendingPlan(
        "Synthetic",
        date(2026, 10, 1),
        9,
        900000,
        0,
        9000,
        (Commitment("Rent", 40000, ("Rent",)),),
        {"components": {"All": 900000}},
    )


def test_pool_protects_bills_once_and_ignores_future_income_and_transfers():
    rows = [
        row("food", "2026-10-05", 10000),
        row("rent", "2026-10-02", 40000, "Rent"),
        row("future", "2026-12-01", 90000),
        row("income", "2026-10-01", 100000, kind="income"),
        row("transfer", "2026-10-01", 100000, kind="transfer"),
        row("refund", "2026-10-06", 1000, kind="refund"),
    ]
    result = spending_summary(plan(), rows, date(2026, 10, 12))
    assert result["month_spent"] == 49000
    assert result["unpaid"] == 320000
    assert result["available"] == 900000 - 49000 - 320000 - 9000
    assert result["month_available"] == 59000 - 9000
    assert result["quarter_available"] == 177000 - 9000
    assert result["projected_year"] >= result["year_spent"]


def test_cross_quarter_rollover_and_previous_year_like_for_like():
    rows = [
        row("prior", "2026-10-05", 10000),
        row("now", "2027-01-05", 20000),
        row("old", "2026-01-05", 15000),
        row("old-later", "2026-01-30", 90000),
    ]
    result = spending_summary(plan(), rows, date(2027, 1, 12))
    assert result["month"]["rollover"] == 167000
    assert result["month_available"] == 167000 + 59000 - 20000
    assert result["previous_year_month"] == 15000
    assert result["year_comparisons"][0]["Net spent"] == 150


def test_empty_outside_plan_leap_day_and_pool_cap():
    assert previous_year(date(2024, 2, 29)) == date(2023, 2, 28)
    assert spending_summary(None, [], date(2026, 10, 1))["previous_year_month"] is None
    assert not spending_summary(plan(), [], date(2028, 1, 1))["active"]
    small = replace(plan(), academic_target_cents=10000)
    result = spending_summary(small, [], date(2026, 10, 1))
    assert result["month_available"] <= result["available"] < 0
    assert result["weekly_guide"] == 0
