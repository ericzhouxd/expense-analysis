"""Synthetic regressions for sorting spending into everyday, bills and big stuff."""

from datetime import date

import pytest

from expense_analysis.config import AppConfig
from expense_analysis.database import Database
from expense_analysis.spending_summary import spending_summary
from expense_analysis.spending_treatment import (
    CATEGORY_DEFAULT,
    apply_transaction_treatment,
    classify_spending,
)
from expense_analysis.term_budget import Bill, BudgetSettings


def budget():
    return BudgetSettings(bills=(Bill("Tuition", 180000, ("Tuition",), "Each quarter"),))


def row(identifier, amount, category="Food", day="2026-10-05", kind="expense"):
    return {
        "id": identifier,
        "amount_cents": amount,
        "category": category,
        "transaction_date": day,
        "transaction_type": kind,
    }


def test_bill_categories_default_to_bills_everywhere_and_exceptions_win():
    rows = [row("old", 180000, "Tuition", "2025-10-05"), row("new", 500)]
    result = classify_spending(rows, budget())
    assert result[0]["spending_treatment"] == "Commitments"
    assert not result[0]["treatment_review"]
    assert result[1]["spending_treatment"] == "Everyday"
    assert result[1]["treatment_review"]
    rules = {"transactions": {"old": {"treatment": "Everyday"}}}
    assert classify_spending(rows, budget(), rules)[0]["spending_treatment"] == "Everyday"
    by_category = {"categories": {"Tuition": "Irregular"}}
    assert classify_spending(rows, budget(), by_category)[0]["spending_treatment"] == "Irregular"


def test_transaction_override_applies_and_resets_to_category_default(tmp_path):
    from expense_analysis.models import TransactionDraft

    db = Database(tmp_path / "rules-synthetic.sqlite")
    db.initialize()
    db.save_budget_settings(budget())
    identifier = db.add_transaction(
        TransactionDraft(date(2026, 10, 5), "Synthetic flight", 60000, "Transportation")
    )
    assert db.get_spending_rules() == {}  # Suggestions do not silently apply.

    rules = apply_transaction_treatment({}, [identifier], "Irregular")
    db.save_spending_rules(rules)
    assert db.get_spending_rules()["transactions"][identifier] == {"treatment": "Irregular"}
    summary = spending_summary(
        db.get_budget_settings(), db.list_transactions(), date(2026, 10, 10), rules
    )
    assert summary["everyday_spent"] == 0
    assert summary["treatment_totals"]["Irregular"] == 60000

    reset = apply_transaction_treatment(rules, [identifier], CATEGORY_DEFAULT)
    assert identifier not in reset["transactions"]
    with pytest.raises(ValueError, match="Tick at least one"):
        apply_transaction_treatment(rules, [], "Everyday")
    with pytest.raises(ValueError, match="Everyday, Bills or Big stuff"):
        apply_transaction_treatment(rules, [identifier], "Savings")


def test_legacy_reserve_names_in_saved_rules_still_load():
    rules = {"transactions": {"x": {"treatment": "Irregular", "reserve": "Travel home"}}}
    assert classify_spending([row("x", 100)], None, rules)[0]["spending_treatment"] == "Irregular"


def test_category_rename_carries_saved_treatment(tmp_path):
    db = Database(tmp_path / "synthetic.sqlite")
    db.initialize()
    from expense_analysis.categories import preferences, save_category

    save_category(db, AppConfig(), "Flight", "Personal")
    db.save_spending_rules({"categories": {"Flight": "Irregular"}, "transactions": {}})
    save_category(db, AppConfig(), "Airfare", "Personal", source="Flight")
    assert db.get_spending_rules()["categories"] == {"Airfare": "Irregular"}
    assert preferences(db)["classes"]["Airfare"] == "Personal"
    with pytest.raises(ValueError):
        db.save_spending_rules({"categories": {"Airfare": "Invalid"}})


def test_week_comparison_matches_weekdays_and_handles_zero_baseline():
    rows = [
        row("old", 1000, day="2026-10-12"),
        row("refund", 1000, day="2026-10-13", kind="refund"),
        row("now", 2000, day="2026-10-19"),
        row("future", 90000, day="2026-10-22"),
    ]
    result = spending_summary(None, rows, date(2026, 10, 21))
    comp = result["everyday_week_comparison"]
    assert comp["change"] == 2000
    assert comp["percent"] is None
    assert comp["start"] == date(2026, 10, 19)
    assert comp["prior_end"] == date(2026, 10, 14)
