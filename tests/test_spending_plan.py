from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from expense_analysis.budget_ui import cents
from expense_analysis.database import Database
from expense_analysis.models import TransactionDraft
from expense_analysis.spending_plan import Commitment, SpendingPlan, calculate_plan, split_cents
from expense_analysis.university_presets import ucla_benchmark

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def plan():
    return SpendingPlan(
        name="Synthetic student",
        start=date(2026, 10, 1),
        months=9,
        academic_target_cents=900000,
        summer_target_cents=0,
        buffer_cents=9000,
        commitments=(
            Commitment("Rent", 40000, ("Rent",)),
            Commitment("Tuition", 90000, ("Tuition",), "Quarterly"),
            Commitment("Insurance", 9000, ("Insurance",), "Coverage total"),
        ),
        reference={
            "school": "UCLA",
            "year": "2026–27",
            "cohort": "2024–25",
            "housing": "Off-campus",
            "residency": "CA resident",
            "source": "https://financialaid.ucla.edu/go/coa",
            "verified_on": "2026-09-08",
            "components": ucla_benchmark("2024–25", "Off-campus", False),
        },
    )


def transaction(identifier, month, amount, category="Food", kind="expense"):
    return {
        "id": identifier,
        "transaction_date": f"{month}-05",
        "amount_cents": amount,
        "category": category,
        "transaction_type": kind,
        "description": "Synthetic only",
    }


def test_benchmark_is_cohort_specific_and_independent():
    resident = ucla_benchmark("2024–25", "Off-campus", False)
    assert sum(resident.values()) == 4663400
    assert sum(ucla_benchmark("2024–25", "Off-campus", True).values()) == 8083400
    resident["Housing"] = 0
    assert ucla_benchmark("2024–25", "Off-campus", False)["Housing"] == 1454100


def test_payment_replaces_reserve_instead_of_double_counting(plan):
    empty = calculate_plan(plan, [])
    paid = calculate_plan(plan, [transaction("tuition", "2026-10", 90000, "Tuition")])
    assert paid["quarters"][0]["allowance"] == empty["quarters"][0]["allowance"] == 84000
    assert paid["quarters"][0]["flexible_spent"] == 0
    assert paid["obligations"][9]["unpaid"] == 0


def test_annual_prepayment_spreads_over_coverage(plan):
    result = calculate_plan(plan, [transaction("insurance", "2026-10", 9000, "Insurance")])
    assert [q["allowance"] for q in result["quarters"]] == [84000] * 3
    assert result["obligations"][-1]["unpaid"] == 0


def test_bill_overrun_reduces_allowance_and_refund_restores_reserve(plan):
    over = transaction("rent", "2026-10", 45000, "Rent")
    result = calculate_plan(plan, [over])
    assert result["quarters"][0]["allowance"] == 79000
    refund = transaction("refund", "2026-10", 7000, "Rent", "refund")
    result = calculate_plan(plan, [over, refund])
    assert result["quarters"][0]["allowance"] == 84000
    assert result["obligations"][0]["unpaid"] == 2000


def test_all_unmatched_expenses_count_income_and_transfers_do_not(plan):
    rows = [
        transaction("food", "2026-10", 10000),
        transaction("unknown", "2026-10", 2000, "Uncategorized"),
        transaction("travel", "2026-10", 3000, "Flight"),
        transaction("refund", "2026-10", 1500, kind="refund"),
        transaction("income", "2026-10", 500000, kind="income"),
        transaction("transfer", "2026-10", 100000, kind="transfer"),
    ]
    month = calculate_plan(plan, rows)["months"][0]
    assert month["flexible_spent"] == 13500
    assert month["remaining"] == 14500


def test_rollover_preserves_positive_and_negative_and_resets_at_quarter(plan):
    result = calculate_plan(plan, [transaction("food", "2026-10", 60000)])
    months = result["months"]
    assert months[0]["remaining"] == -32000
    assert months[1]["rollover"] == -32000
    assert months[1]["remaining"] == -4000
    assert months[2]["remaining"] == result["quarters"][0]["remaining"] == 24000
    assert months[3]["rollover"] == 0


def test_payment_before_plan_can_be_assigned_without_changing_transaction(plan):
    row = transaction("prepaid", "2026-09", 95000, "Tuition")
    allocated = replace(plan, allocations={"prepaid": "2026-10"})
    assert calculate_plan(plan, [row])["quarters"][0]["allowance"] == 84000
    result = calculate_plan(allocated, [row])
    assert result["quarters"][0]["allowance"] == 79000
    assert row["transaction_date"] == "2026-09-05"
    assert result["transactions"][0]["budget_month"] == "2026-10"


def test_summer_is_added_not_nine_month_budget_divided_by_twelve(plan):
    extended = replace(
        plan,
        months=12,
        summer_target_cents=120000,
        buffer_cents=0,
        commitments=(Commitment("Rent", 40000, ("Rent",), months=12),),
    )
    result = calculate_plan(extended, [])
    assert result["quarters"][0]["target"] == 300000
    assert result["quarters"][3]["target"] == 120000
    assert result["quarters"][3]["allowance"] == 0
    assert sum(q["target"] for q in result["quarters"]) == extended.total_target_cents


@pytest.mark.parametrize("target", [1, 900001, 900002, 900007])
def test_cent_exact_totals_even_when_budget_is_negative(plan, target):
    result = calculate_plan(replace(plan, academic_target_cents=target), [])
    assert sum(m["target"] for m in result["months"]) == target
    for index, quarter in enumerate(result["quarters"]):
        months = result["months"][index * 3 : index * 3 + 3]
        assert sum(m["allowance"] for m in months) == quarter["allowance"]
        assert months[-1]["remaining"] == quarter["remaining"]
    assert sum(split_cents(-7, 3)) == -7


def test_overlapping_category_mapping_is_rejected(plan):
    with pytest.raises(ValueError, match="overlapping"):
        replace(plan, commitments=(*plan.commitments, Commitment("Other", 1, ("Rent",)))).validate()
    replace(
        plan,
        commitments=(
            Commitment("Fall", 1, ("Rent",), months=3),
            Commitment("Winter", 2, ("Rent",), first_month=3, months=3),
        ),
    ).validate()


@pytest.mark.parametrize(
    "changes",
    [
        {"academic_target_cents": -1},
        {"buffer_cents": 1.2},
        {"summer_target_cents": 100},
        {"months": 10},
        {"start": date(2026, 10, 5)},
        {"allocations": {"x": "2000-01"}},
        {"commitments": (Commitment("Too long", 1, (), months=12),)},
        {"commitments": (Commitment("Partial", 1, (), "Quarterly", months=4),)},
    ],
)
def test_invalid_plan_is_rejected(plan, changes):
    with pytest.raises(ValueError):
        replace(plan, **changes).validate()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -10, None, "oops"])
def test_invalid_ui_money_is_rejected(value):
    with pytest.raises(ValueError):
        cents(value)


def test_persistence_is_additive_and_roundtrips(plan, tmp_path):
    database = Database(tmp_path / "synthetic.sqlite3")
    database.initialize()
    assert database.get_spending_plan() is None
    database.add_transaction(
        TransactionDraft(
            transaction_date=date(2026, 10, 1),
            description="Synthetic",
            amount_cents=1000,
            category="Food",
            account="Checking",
            payment_method="Card",
        )
    )
    database.save_spending_plan(plan)
    database.initialize()
    assert database.get_spending_plan() == plan
    assert database.count_transactions() == 1
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    database.save_spending_plan(replace(plan, buffer_cents=0))
    saved = database.get_spending_plan()
    assert saved is not None
    assert saved.buffer_cents == 0


def test_initialize_drops_the_legacy_budgets_table(tmp_path):
    database = Database(tmp_path / "legacy.sqlite3")
    database.initialize()

    # Restore the pre-schema-3 shape: a budgets table holding a row.
    with database.connect() as connection:
        connection.execute(
            """CREATE TABLE budgets (
                month TEXT NOT NULL,
                category TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
                PRIMARY KEY (month, category)
            )"""
        )
        connection.execute(
            "INSERT INTO budgets (month, category, amount_cents) VALUES ('2026-07', 'Food', 30000)"
        )
        connection.execute("PRAGMA user_version = 2")

    database.initialize()

    with database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert version == 3
    assert "budgets" not in tables
    assert "spending_plans" in tables


def test_setup_and_all_pages_use_synthetic_database(plan, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from expense_analysis import ui
    from expense_analysis.config import AppConfig

    database = Database(tmp_path / "ui.sqlite3")
    database.initialize()
    monkeypatch.setattr(ui, "_database", lambda: database)
    monkeypatch.setattr(ui, "load_config", AppConfig)
    app = AppTest.from_file(APP_PATH).run()
    app.radio[0].set_value("Budgets").run()
    assert not app.exception
    assert database.get_spending_plan() is None
    next(b for b in app.button if b.label == "Save spending plan").click().run()
    assert app.error and database.get_spending_plan() is None
    next(s for s in app.selectbox if s.label == "Tuition residency").set_value("CA resident").run()
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "Save spending plan").click().run()
    assert not app.exception
    saved = database.get_spending_plan()
    assert saved is not None
    assert saved.reference["cohort"] == "2024–25"
    database.save_spending_plan(plan)
    database.add_transaction(
        TransactionDraft(
            transaction_date=date(2026, 10, 5),
            description="Synthetic lunch",
            amount_cents=1000,
            category="Food",
            account="Checking",
            payment_method="Card",
        )
    )
    # A fresh session also verifies that the saved plan is loaded from SQLite.
    app = AppTest.from_file(APP_PATH).run()
    next(field for field in app.text_input if field.label == "Search").set_value(
        "no matching transaction"
    ).run()
    assert not app.exception
    app.radio[0].set_value("Budgets").run()
    next(r for r in app.radio if r.label == "View").set_value("Quarterly").run()
    assert not app.exception
    assert any(
        'Everyday spent</dt><dd class="numeric">$10.00</dd>' in block.proto.body
        for block in app.get("html")
    )
    # The hidden activity search must not hide spending from the budget.
    assert not any(field.label == "Search" for field in app.text_input)
    for page in [
        "Overview",
        "Transactions",
        "Import / Export",
        "Budgets",
        "Advanced insights",
        "Settings",
    ]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
        assert all("<div" not in block.value for block in app.code), page


def render_saved_plan_setup(database, plan):
    from expense_analysis.budget_ui import _setup
    from expense_analysis.config import AppConfig

    _setup(database, plan, AppConfig())


def test_budget_category_choices_preserve_commas_when_resaved(plan, tmp_path):
    from streamlit.testing.v1 import AppTest

    database = Database(tmp_path / "category-plan.sqlite3")
    database.initialize()
    updated = replace(plan, commitments=(Commitment("Studio", 1000, ("Art, materials",)),))
    database.save_spending_plan(updated)
    app = AppTest.from_function(render_saved_plan_setup, args=(database, updated)).run()
    app.checkbox[0].check()
    next(button for button in app.button if button.label == "Save spending plan").click().run()
    assert not app.exception and not app.error
    saved = database.get_spending_plan()
    assert saved is not None
    assert saved.commitments[0].categories == ("Art, materials",)
