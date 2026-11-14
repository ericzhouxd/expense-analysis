from datetime import date, timedelta

import pytest

from expense_analysis.analytics import (
    monthly_spending,
    period_metrics,
    recurring_transactions,
    savings_summary,
    spending_anomalies,
    spending_drivers,
    spending_forecast,
    transactions_frame,
    weekly_spending,
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
    forecast = spending_forecast(frame, date(2026, 7, 30))
    assert forecast.months.empty
    assert forecast.history_months == 0
    assert forecast.typical_miss is None


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
    extended = monthly_spending(frame, through=date(2026, 5, 2))
    assert extended["spending"].tolist() == [100.0, 0.0, 200.0, 0.0, 0.0]
    assert extended["rolling_3"].iloc[-1] == pytest.approx(200 / 3)
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


def test_spending_drivers_keep_the_last_days_of_a_complete_month():
    frame = transactions_frame(
        [row("1", "2026-02-10", 1000), row("2", "2026-03-30", 5000)], AppConfig()
    )
    drivers = spending_drivers(frame, date(2026, 3, 31))
    assert drivers.iloc[0]["current"] == 50
    assert drivers.iloc[0]["previous"] == 10


def test_recurring_detects_more_cycles_and_flags_stopped_charges():
    rows = [
        row("b1", "2026-01-02", 1500, description="Gym biweekly"),
        row("b2", "2026-01-16", 1500, description="Gym biweekly"),
        row("b3", "2026-01-30", 1500, description="Gym biweekly"),
        row("y1", "2023-05-01", 9900, description="Domain #48213"),
        row("y2", "2024-05-01", 9900, description="Domain #51122"),
        row("y3", "2025-05-01", 9900, description="Domain #60001"),
        row("s1", "2026-03-01", 450, description="7-Eleven"),
        row("s2", "2026-03-08", 450, description="7-Eleven"),
        row("s3", "2026-03-15", 450, description="7-Eleven"),
    ]
    recurring = recurring_transactions(transactions_frame(rows, AppConfig()), date(2026, 3, 20))
    by_name = recurring.set_index("merchant")
    assert by_name.loc["Gym Biweekly", "frequency"] == "Biweekly"
    assert by_name.loc["Gym Biweekly", "status"] == "Possibly stopped"
    assert by_name.loc["Domain", "frequency"] == "Yearly"
    assert by_name.loc["Domain", "next_expected"] == date(2026, 5, 1)
    assert by_name.loc["7-Eleven", "status"] == "Active"


def test_forecast_needs_two_complete_months():
    frame = transactions_frame(
        [row("1", "2026-01-05", 10000), row("2", "2026-02-05", 5000)], AppConfig()
    )
    forecast = spending_forecast(frame, date(2026, 2, 10))
    assert forecast.history_months == 1
    assert forecast.months.empty


def test_forecast_of_a_steady_ledger_is_flat_and_keeps_what_is_spent():
    frame = transactions_frame(
        [
            row("1", "2026-01-01", 30000),
            row("2", "2026-02-01", 30000),
            row("3", "2026-03-01", 30000),
            row("4", "2026-04-10", 15000),
            row("5", "2026-04-11", 99900, transaction_type="income"),
            row("6", "2026-04-12", 99900, transaction_type="transfer"),
        ],
        AppConfig(),
    )
    forecast = spending_forecast(frame, date(2026, 4, 15))
    assert forecast.level == pytest.approx(300)
    assert forecast.typical_miss == pytest.approx(0)
    assert forecast.history_months == 3
    months = forecast.months
    assert [str(month) for month in months["month"]] == ["2026-04", "2026-05", "2026-06", "2026-07"]
    assert months["partial"].tolist() == [True, False, False, False]
    # Half of April is left: $150 spent, on the usual pace, lands on the usual $300.
    assert months["expected"].tolist() == pytest.approx([300, 300, 300, 300])
    assert months["spent"].tolist() == pytest.approx([150, 0, 0, 0])
    assert months["low"].tolist() == pytest.approx([300, 300, 300, 300])


def test_forecast_weighs_recent_months_and_widens_with_distance():
    frame = transactions_frame(
        [
            row("1", "2026-01-03", 10000),
            row("2", "2026-02-03", 22000),
            row("3", "2026-02-20", 2000, transaction_type="refund"),
        ],
        AppConfig(),
    )
    forecast = spending_forecast(frame, date(2026, 2, 28), horizon=2)
    # February (200 net) counts 1, January (100) counts 0.6.
    assert forecast.level == pytest.approx(162.5)
    # January alone would have predicted 100 for February, which came in at 200.
    assert forecast.typical_miss == pytest.approx(100)
    months = forecast.months
    assert [str(month) for month in months["month"]] == ["2026-03", "2026-04"]
    assert months["low"].tolist() == pytest.approx([62.5, 162.5 - 100 * 1.16**0.5])
    assert months["high"].tolist() == pytest.approx([262.5, 162.5 + 100 * 1.16**0.5])


def test_forecast_range_never_goes_below_zero_or_below_what_is_spent():
    frame = transactions_frame(
        [
            row("1", "2026-01-02", 1000),
            row("2", "2026-02-02", 90000),
            row("3", "2026-03-02", 1000),
            row("4", "2026-04-02", 40000),
        ],
        AppConfig(),
    )
    months = spending_forecast(frame, date(2026, 4, 3)).months
    assert months["low"].tolist()[0] >= 400
    assert (months["low"] >= 0).all()
    assert (months["high"] >= months["expected"]).all()


def _daily_rows(start: date, end: date, cents_for) -> list[dict]:
    rows = []
    day = start
    while day <= end:
        rows.append(row(day.isoformat(), day.isoformat(), cents_for(day)))
        day += timedelta(days=1)
    return rows


def test_forecast_follows_the_school_calendar_when_given_one():
    def kind_of(day: date) -> str | None:
        return "summer" if day.month in (7, 8) else "quarter"

    # $10 a day in term, $4 a day over the summer.
    frame = transactions_frame(
        _daily_rows(
            date(2025, 9, 1), date(2026, 9, 30), lambda day: 400 if day.month in (7, 8) else 1000
        ),
        AppConfig(),
    )
    aware = spending_forecast(frame, date(2026, 9, 30), horizon=10, kind_of=kind_of)
    plain = spending_forecast(frame, date(2026, 9, 30), horizon=10)
    months = {str(item["month"]): item["expected"] for _, item in aware.months.iterrows()}
    # The summer just ended, so a plain forecast is dragged down for October.
    assert months["2026-10"] > plain.months["expected"].iloc[0]
    assert months["2026-10"] == pytest.approx(310, rel=0.1)
    assert months["2027-07"] == pytest.approx(124, rel=0.2)
    assert plain.months["expected"].nunique() == 1
    assert plain.weekly_rates == {}
    assert aware.weekly_rates["quarter"] == pytest.approx(70, rel=0.1)
    assert aware.weekly_rates["summer"] == pytest.approx(28, rel=0.2)
    # Knowing the calendar is what makes the replayed forecasts miss less.
    assert aware.typical_miss is not None and plain.typical_miss is not None
    assert aware.typical_miss < plain.typical_miss


def test_forecast_treats_days_off_the_calendar_as_ordinary():
    frame = transactions_frame(
        _daily_rows(date(2026, 1, 1), date(2026, 4, 30), lambda day: 1000), AppConfig()
    )
    forecast = spending_forecast(frame, date(2026, 4, 30), kind_of=lambda day: None)
    assert forecast.weekly_rates == {}
    assert forecast.months["expected"].tolist() == pytest.approx([300, 300, 300], rel=0.02)


def test_weekly_spending_fills_quiet_weeks_and_runs_through_today():
    frame = transactions_frame(
        [
            row("1", "2026-11-02", 4000),  # a Monday
            row("2", "2026-11-08", 1000),  # the Sunday of the same week
            row("3", "2026-11-17", 2000),
            row("4", "2026-11-18", 9900, transaction_type="transfer"),
        ],
        AppConfig(),
    )
    weekly = weekly_spending(frame, through=date(2026, 12, 2))
    assert weekly["week"].tolist() == [
        date(2026, 11, 2),
        date(2026, 11, 9),
        date(2026, 11, 16),
        date(2026, 11, 23),
        date(2026, 11, 30),
    ]
    assert weekly["spending"].tolist() == [50.0, 0.0, 20.0, 0.0, 0.0]
    assert weekly["rolling_4"].iloc[3] == pytest.approx(17.5)
    assert weekly_spending(transactions_frame([], AppConfig())).empty


def test_forecast_skips_a_first_month_that_started_late():
    frame = transactions_frame(
        [
            row("1", "2026-01-20", 5000),
            row("2", "2026-02-02", 30000),
            row("3", "2026-03-02", 30000),
        ],
        AppConfig(),
    )
    forecast = spending_forecast(frame, date(2026, 4, 10))
    assert forecast.history_months == 2
    assert forecast.level == pytest.approx(300)
