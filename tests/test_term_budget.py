"""The weekly line on UCLA's calendar, with synthetic transactions only."""

import json
from datetime import date, timedelta

import pytest

from expense_analysis.database import Database
from expense_analysis.term_budget import (
    Bill,
    BudgetSettings,
    period_for,
    period_totals,
    school_periods,
    school_weeks,
    term_budget,
    weekly_line,
)
from expense_analysis.university_presets import everyday_estimate

TODAY = date(2026, 11, 9)  # Monday of Fall 2026 week 7


def row(identifier, day, amount, category="Food", kind="expense"):
    return {
        "id": identifier,
        "transaction_date": day,
        "amount_cents": amount,
        "category": category,
        "transaction_type": kind,
    }


def test_periods_cover_every_day_and_quarters_are_week_zero_ten_weeks_and_finals():
    periods = school_periods()
    for before, after in zip(periods, periods[1:], strict=False):
        assert after.start == before.end + timedelta(days=1)
    for period in periods:
        assert period.start.weekday() == 0 and period.end.weekday() == 6
    fall = period_for(date(2026, 10, 1))
    assert fall.name == "Fall quarter 2026"
    assert [fall.label(w) for w in fall.weeks] == [
        "Week 0",
        *(f"Week {n}" for n in range(1, 11)),
        "Finals week",
    ]
    winter = period_for(date(2027, 2, 1))
    assert len(winter.weeks) == 11 and winter.label(winter.weeks[0]) == "Week 1"
    assert period_for(date(2026, 12, 20)).name == "Winter break 2026"
    assert period_for(date(2027, 3, 24)).name == "Spring break 2027"
    assert period_for(date(2026, 7, 4)).kind == "summer"
    assert period_for(TODAY).label(TODAY) == "Week 7"
    outside = period_for(date(2030, 5, 15))
    assert outside.kind == "month" and outside.start.weekday() == 0


def test_school_line_spreads_ucla_everyday_estimate_over_the_school_year():
    assert school_weeks() == 38
    estimate = everyday_estimate("Off-campus")
    line = weekly_line(BudgetSettings())
    assert (
        line["school_yearly"]
        == estimate["Food"] + estimate["Transportation"] + estimate["Personal"]
    )
    assert line["weekly"] == round(line["school_yearly"] / 38)
    assert line["source"] == "school"
    own = weekly_line(BudgetSettings(weekly_cents=20000))
    assert own["weekly"] == 20000 and own["source"] == "own"


def test_each_week_starts_fresh_and_leftover_is_saved_not_carried():
    settings = BudgetSettings(weekly_cents=10000)
    rows = [
        row("w5", "2026-10-28", 4000),  # week 5: 60.00 saved
        row("w6", "2026-11-03", 13000),  # week 6: 30.00 over
        row("refund", "2026-11-04", 1000, kind="refund"),
        row("today", "2026-11-09", 2500),
        row("future", "2026-11-12", 9000),
        row("income", "2026-11-09", 50000, kind="income"),
        row("transfer", "2026-11-09", 50000, kind="transfer"),
    ]
    result = term_budget(settings, rows, TODAY)
    week = result["week"]
    assert week["label"] == "Week 7"
    assert week["line"] == 10000  # not raised by week 5's leftover
    assert week["spent"] == 2500
    assert week["left"] == 7500
    assert week["days_left"] == 7 and week["per_day"] == 7500 // 7
    by_label = {w["label"]: w for w in result["weeks"]}
    assert by_label["Week 5"]["saved"] == 6000
    assert by_label["Week 6"]["saved"] == -2000
    assert by_label["Week 7"]["saved"] is None
    assert by_label["Week 8"]["state"] == "future" and by_label["Week 8"]["spent"] == 0
    assert result["totals"]["saved"] == 7 * 10000 - 4000 - 12000
    assert result["totals"]["weeks_done"] == 7


def test_bills_and_big_stuff_stay_outside_the_line():
    settings = BudgetSettings(
        weekly_cents=10000,
        bills=(
            Bill("Rent", 145000, ("Rent",), "Monthly", due_day=1),
            Bill("Phone", 3000, ("Phone",), "Monthly", due_day=20),
            Bill("Tuition", 440000, ("Tuition",), "Each quarter"),
        ),
    )
    rows = [
        row("rent", "2026-11-01", 145000, "Rent"),
        row("tuition", "2026-09-15", 440000, "Tuition"),
        row("flight", "2026-11-09", 30000, "Flights"),
        row("lunch", "2026-11-09", 1200),
    ]
    rules = {"categories": {"Flights": "Irregular"}}
    result = term_budget(settings, rows, TODAY, rules)
    assert result["week"]["spent"] == 1200
    assert result["totals"]["bills"] == 145000  # tuition was paid before week 0
    assert result["totals"]["big_stuff"] == 30000
    assert [r["id"] for r in result["big_stuff"]] == ["flight"]
    bills = {(b["name"], b["due"]): b for b in result["bills"]}
    assert bills["Rent", date(2026, 11, 1)]["status"] == "paid"
    # October's rent shows no payment, but November's is paid, so it stops nagging.
    assert bills["Rent", date(2026, 10, 1)]["status"] == "missed"
    assert bills["Rent", date(2026, 12, 1)]["status"] == "upcoming"
    assert bills["Phone", date(2026, 11, 20)]["status"] == "upcoming"
    assert bills["Tuition", date(2026, 9, 21)]["status"] == "paid"


def test_school_year_compares_spending_with_the_estimate_to_date():
    rows = [row("a", "2026-09-22", 5000), row("b", "2026-11-09", 1000)]
    year = term_budget(None, rows, TODAY)["year"]
    assert year["label"] == "2026–27"
    assert year["start"] == date(2026, 9, 21) and year["end"] == date(2027, 6, 13)
    assert year["spent"] == 6000
    assert 0 < year["estimate_to_date"] < year["estimate"]
    assert year["weeks_done"] == 7
    assert term_budget(None, [], date(2030, 1, 1))["year"] is None


def test_viewing_a_past_term_and_period_totals():
    rows = [row("spring", "2026-04-02", 5000), row("break", "2026-03-25", 700)]
    spring = term_budget(BudgetSettings(weekly_cents=10000), rows, TODAY, day=date(2026, 4, 1))
    assert spring["period"]["name"] == "Spring quarter 2026"
    assert spring["period"]["is_current"] is False
    assert spring["week"] is None
    assert all(w["state"] == "past" for w in spring["weeks"])
    assert spring["totals"]["everyday"] == 5000
    totals = {t["period"]: t["spent"] for t in period_totals(rows, TODAY)}
    assert totals == {"Spring break 2026": 700, "Spring quarter 2026": 5000}


def test_settings_validate_roundtrip_and_convert_a_month_plan(tmp_path):
    with pytest.raises(ValueError, match="two bills"):
        BudgetSettings(bills=(Bill("A", 1, ("Rent",)), Bill("B", 1, ("Rent",)))).validate()
    with pytest.raises(ValueError, match="date it is due"):
        BudgetSettings(bills=(Bill("Books", 1, (), "Once"),)).validate()
    with pytest.raises(ValueError, match="more than"):
        BudgetSettings(weekly_cents=0).validate()
    with pytest.raises(ValueError, match="housing|campus"):
        BudgetSettings(housing="Castle").validate()

    database = Database(tmp_path / "budget.sqlite3")
    database.initialize()
    assert database.get_budget_settings() is None
    settings = BudgetSettings(
        housing="On-campus",
        weekly_cents=25000,
        bills=(Bill("Fees", 9000, ("School Fees",), "Once", due=date(2026, 12, 1)),),
    )
    database.save_budget_settings(settings)
    assert database.get_budget_settings() == settings

    legacy = {
        "schema_version": 2,
        "name": "Old plan",
        "start": "2026-10-01",
        "months": 9,
        "academic_target_cents": 900000,
        "summer_target_cents": 0,
        "buffer_cents": 0,
        "reference": {"housing": "Commuter"},
        "allocations": {},
        "commitments": [
            {"name": "Rent", "amount_cents": 80000, "categories": ["Rent"], "cadence": "Monthly"},
            {
                "name": "Tuition",
                "amount_cents": 1000,
                "categories": ["Tuition"],
                "cadence": "Coverage total",
                "first_month": 2,
            },
            {
                "name": "Trip",
                "amount_cents": 5000,
                "categories": ["Flights"],
                "cadence": "Coverage total",
                "treatment": "Irregular",
            },
        ],
    }
    with database.connect() as connection:
        connection.execute(
            "UPDATE spending_plans SET payload = ? WHERE id = 1", (json.dumps(legacy),)
        )
    converted = database.get_budget_settings()
    assert converted is not None
    assert converted.housing == "Commuter" and converted.weekly_cents is None
    assert [(b.name, b.cadence, b.due) for b in converted.bills] == [
        ("Rent", "Monthly", None),
        ("Tuition", "Once", date(2026, 12, 1)),
    ]


def test_bill_payments_settle_the_nearest_due_date_and_allow_for_cents():
    settings = BudgetSettings(
        bills=(
            Bill("Rent", 145000, ("Rent",), "Monthly", due_day=1),
            Bill("Phone", 3500, ("Phone",), "Monthly", due_day=20),
            Bill("Utilities", 6000, ("Utilities",), "Monthly", due_day=15),
        )
    )
    rows = [
        # Paid two days early, in the month before the due date.
        row("rent", "2026-10-30", 145000, "Rent"),
        # A few cents under the amount entered for the bill.
        row("phone", "2026-10-19", 3487, "Phone"),
        # Well under the estimate: something was paid, but not the whole amount.
        row("power", "2026-10-14", 3100, "Utilities"),
    ]
    result = term_budget(settings, rows, TODAY)
    bills = {(b["name"], b["due"]): b for b in result["bills"]}
    assert bills["Rent", date(2026, 11, 1)]["status"] == "paid"
    assert bills["Rent", date(2026, 10, 1)]["status"] == "missed"
    assert bills["Phone", date(2026, 10, 20)]["status"] == "paid"
    assert bills["Utilities", date(2026, 10, 15)]["status"] == "part"
    rent = bills["Rent", date(2026, 11, 1)]
    assert (rent["window_start"], rent["window_end"]) == (date(2026, 10, 17), date(2026, 11, 16))
    # What needs attention comes first; settled due dates sink to the bottom.
    statuses = [b["status"] for b in result["bills"]]
    assert statuses.index("part") < statuses.index("upcoming") < statuses.index("paid")
    assert result["bill_totals"]["paid"] == 2
    # The rest of October's utilities, then November's utilities and phone and December's rent.
    assert result["bill_totals"]["outstanding"] == (6000 - 3100) + 6000 + 3500 + 145000


def test_period_kinds_follow_the_calendar():
    from expense_analysis.term_budget import period_kind_lookup

    kind = period_kind_lookup()
    assert kind(date(2026, 11, 9)) == "quarter"
    assert kind(date(2026, 12, 20)) == "break"
    assert kind(date(2026, 7, 15)) == "summer"
    assert kind(date(2024, 1, 1)) is None
