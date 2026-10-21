from dataclasses import replace
from datetime import date

import pytest

from expense_analysis.categories import (
    effective_config,
    preferences,
    save_category,
    suggestion_data,
)
from expense_analysis.config import AppConfig
from expense_analysis.database import Database
from expense_analysis.import_export import preview_csv
from expense_analysis.models import TransactionDraft
from expense_analysis.spending_plan import Commitment, SpendingPlan


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "categories.sqlite3")
    database.initialize()
    return database


def test_rename_updates_history_fingerprint_plan_and_import_alias(database):
    config = AppConfig()
    draft = TransactionDraft(date(2026, 10, 2), "Synthetic", 1200, "Food")
    identifier = database.add_transaction(draft)
    plan = SpendingPlan(
        "Test",
        date(2026, 10, 1),
        9,
        90000,
        0,
        0,
        (Commitment("Food reserve", 1000, ("Food",)),),
        {},
    )
    database.save_spending_plan(plan)
    assert (
        save_category(database, config, "Everyday", "Personal", source="Food", keyword="groceries")
        == 1
    )
    saved = database.get_transaction(identifier)
    assert saved["category"] == "Everyday"
    assert saved["fingerprint"] == replace(draft, category="Everyday").fingerprint
    assert database.get_spending_plan().commitments[0].categories == ("Everyday",)
    updated = effective_config(database, config)
    assert "Food" not in updated.categories
    assert updated.category_for("", provided="Food") == "Everyday"
    assert updated.category_for("groceries") == "Everyday"
    save_category(database, updated, "Daily", "Personal", source="Everyday")
    assert effective_config(database, config).category_for("", provided="Food") == "Daily"


def test_conflicting_budget_merge_rolls_back_everything(database):
    config = AppConfig()
    database.add_transaction(TransactionDraft(date(2026, 10, 2), "Synthetic", 1000, "Food"))
    plan = SpendingPlan(
        "Test",
        date(2026, 10, 1),
        9,
        90000,
        0,
        0,
        (Commitment("Food", 1000, ("Food",)), Commitment("Rent", 2000, ("Rent",))),
        {},
    )
    database.save_spending_plan(plan)
    with pytest.raises(ValueError, match="overlapping"):
        save_category(database, config, "Rent", "Fixed", source="Food")
    assert database.list_transactions()[0]["category"] == "Food"
    assert database.get_spending_plan() == plan
    assert not preferences(database)["aliases"]


def test_custom_categories_work_without_transactions_and_merchant_history_is_conservative(database):
    config = AppConfig()
    save_category(database, config, "Hobbies", "Personal", keyword="craft")
    updated = effective_config(database, config)
    assert updated.spending_class("Hobbies") == "Personal"
    assert updated.category_for("craft paper") == "Hobbies"
    for i, category in enumerate(("Food", "Food", "Medicine")):
        database.add_transaction(
            TransactionDraft(
                date(2026, 10, i + 1), f"Synthetic {i}", 1000, category, merchant="Mixed store"
            )
        )
    assert "mixed store" not in suggestion_data(database, updated)["merchants"]
    database.add_transaction(
        TransactionDraft(date(2026, 10, 5), "Another", 1000, "Food", merchant="Food store")
    )
    database.add_transaction(
        TransactionDraft(date(2026, 10, 6), "Another 2", 1000, "Food", merchant="Food store")
    )
    assert suggestion_data(database, updated)["merchants"]["food store"] == "Food"


def test_merchant_history_auto_detects_categories_during_import(database):
    config = AppConfig()
    for day in (1, 2, 3):
        database.add_transaction(
            TransactionDraft(
                date(2026, 10, day), "Synthetic", 1000, "Food", merchant="Green Grocer"
            )
        )
    suggestions = suggestion_data(database, config)["merchants"]
    preview = preview_csv(
        b"Description,Date,Amount,Category,Merchant\n"
        b"Synthetic,2026-10-10,9.99,Surprise,Green Grocer\n",
        config,
        merchant_suggestions=suggestions,
    )
    assert preview.valid_drafts[0].category == "Food"


def test_save_time_suggestion_matches_live_priority(database):
    from expense_analysis.categories import suggested_category

    config = AppConfig(category_rules=(("coffee beans", "Food"),))
    assert suggested_category(database, config, "Coffee beans", "Coffee shop") == "Food"
    assert suggested_category(database, config, "coffee", "") == "Dining Out"
    assert suggested_category(database, config, "unmatched synthetic", "") == "Uncategorized"
