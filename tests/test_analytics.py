from datetime import date

import pytest

from expense_analysis.analytics import (
    monthly_spending,
    period_metrics,
    recurring_transactions,
    savings_summary,
    spending_anomalies,
    spending_drivers,
    transactions_frame,
)
from expense_analysis.config import AppConfig


def row(
    row_id,
    transaction_date,
    amount_cents,
    category="Food",
    transaction_type="expense",
    description="Purchase",
):
    return {
        "id": row_id,
        "transaction_date": transaction_date,
        "description": description,
        "amount_cents": amount_cents,
        "category": category,
        "account": "Checking",
        "payment_method": "Card",
        "merchant": "",
        "transaction_type": transaction_type,
        "notes": "",
        "fingerprint": row_id,
        "created_at": transaction_date,
        "updated_at": transaction_date,
    }


def test_empty_analytics_are_safe():
    frame = transactions_frame([], AppConfig())
    metrics = period_metrics(frame, date(2026, 7, 30))
    assert metrics.spending == 0
    assert monthly_spending(frame).empty
    assert spending_anomalies(frame).empty


def test_monthly_average_includes_zero_months():
    frame = transactions_frame(
        [
            row("1", "2026-01-10", 10000),
            row("2", "2026-03-10", 20000),
        ],
        AppConfig(),
    )
    monthly = monthly_spending(frame)
    assert monthly["spending"].tolist() == [100.0, 0.0, 200.0]
    assert period_metrics(frame, date(2026, 3, 10)).monthly_average == 100.0


def test_personal_metrics_exclude_fixed_costs():
    frame = transactions_frame(
        [
            row("1", "2026-03-10", 10000, category="Food"),
            row("2", "2026-03-10", 500000, category="Tuition"),
        ],
        AppConfig(),
    )
    assert period_metrics(frame, date(2026, 3, 31), personal_only=True).spending == 100


def test_refunds_reduce_spending_and_income_improves_cash_flow():
    frame = transactions_frame(
        [
            row("1", "2026-07-01", 10000),
            row("2", "2026-07-02", 2000, transaction_type="refund"),
            row("3", "2026-07-03", 50000, transaction_type="income"),
        ],
        AppConfig(),
    )
    summary = savings_summary(frame)
    assert summary["income"] == 500
    assert summary["net_outflow"] == 80
    assert summary["savings"] == 420
    assert summary["savings_rate"] == pytest.approx(84)


def test_recurring_charge_detection():
    frame = transactions_frame(
        [
            row("1", "2026-01-01", 999, description="Music subscription"),
            row("2", "2026-02-01", 999, description="Music subscription"),
            row("3", "2026-03-01", 999, description="Music subscription"),
        ],
        AppConfig(),
    )
    recurring = recurring_transactions(frame)
    assert recurring.iloc[0]["frequency"] == "Monthly"
    assert recurring.iloc[0]["average_amount"] == 9.99


def test_anomaly_and_spending_driver_detection():
    frame = transactions_frame(
        [
            row("1", "2026-06-01", 1000),
            row("2", "2026-06-08", 1100),
            row("3", "2026-06-15", 900),
            row("4", "2026-07-01", 1000),
            row("5", "2026-07-08", 10000),
        ],
        AppConfig(),
    )
    anomalies = spending_anomalies(frame)
    assert anomalies.iloc[0]["amount"] == 100

    drivers = spending_drivers(frame, date(2026, 7, 31))
    assert drivers.iloc[0]["change"] == 80
