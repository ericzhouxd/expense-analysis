from datetime import date

from expense_analysis.spending_summary import previous_year, spending_summary
from expense_analysis.term_budget import Bill, BudgetSettings


def row(identifier, day, amount, category="Food", kind="expense"):
    return dict(
        id=identifier,
        transaction_date=day,
        amount_cents=amount,
        category=category,
        transaction_type=kind,
    )


def test_month_totals_split_by_treatment_and_ignore_future_income_and_transfers():
    rows = [
        row("food", "2026-10-05", 10000),
        row("rent", "2026-10-02", 40000, "Rent"),
        row("future", "2026-12-01", 90000),
        row("income", "2026-10-01", 100000, kind="income"),
        row("transfer", "2026-10-01", 100000, kind="transfer"),
        row("refund", "2026-10-06", 1000, kind="refund"),
    ]
    budget = BudgetSettings(bills=(Bill("Rent", 40000, ("Rent",)),))
    result = spending_summary(budget, rows, date(2026, 10, 12))
    assert result["month_spent"] == 49000
    assert result["everyday_spent"] == 9000
    assert result["treatment_totals"] == {"Everyday": 9000, "Commitments": 40000, "Irregular": 0}
    # Food has no reviewed treatment yet; the bill category does.
    assert result["review_count"] == 2


def test_previous_year_like_for_like():
    rows = [
        row("now", "2027-01-05", 20000),
        row("old", "2026-01-05", 15000),
        row("old-later", "2026-01-30", 90000),
    ]
    result = spending_summary(None, rows, date(2027, 1, 12))
    assert result["previous_year_month"] == 15000
    assert result["everyday_year_comparison"]["previous"] == 15000


def test_empty_ledger_and_leap_day():
    assert previous_year(date(2024, 2, 29)) == date(2023, 2, 28)
    result = spending_summary(None, [], date(2026, 10, 1))
    assert result["previous_year_month"] is None
    assert result["month_spent"] == 0
