from dataclasses import replace
from datetime import date

import pytest

from expense_analysis.categories import (
    category_history,
    effective_config,
    preferences,
    save_category,
    suggest_category,
)
from expense_analysis.config import AppConfig
from expense_analysis.database import Database
from expense_analysis.import_export import preview_csv
from expense_analysis.models import TransactionDraft
from expense_analysis.term_budget import Bill, BudgetSettings

TODAY = date(2026, 10, 12)


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "categories.sqlite3")
    database.initialize()
    return database


def test_rename_updates_history_fingerprint_bills_and_import_alias(database):
    config = AppConfig()
    draft = TransactionDraft(date(2026, 10, 2), "Synthetic", 1200, "Food")
    identifier = database.add_transaction(draft)
    database.save_budget_settings(BudgetSettings(bills=(Bill("Food bill", 1000, ("Food",)),)))
    assert (
        save_category(database, config, "Everyday", "Personal", source="Food", keyword="groceries")
        == 1
    )
    saved = database.get_transaction(identifier)
    assert saved["category"] == "Everyday"
    assert saved["fingerprint"] == replace(draft, category="Everyday").fingerprint
    assert database.get_budget_settings().bills[0].categories == ("Everyday",)
    updated = effective_config(database, config)
    assert "Food" not in updated.categories
    assert updated.category_for("", provided="Food") == "Everyday"
    assert updated.category_for("groceries") == "Everyday"
    save_category(database, updated, "Daily", "Personal", source="Everyday")
    assert effective_config(database, config).category_for("", provided="Food") == "Daily"


def test_conflicting_budget_merge_rolls_back_everything(database):
    config = AppConfig()
    database.add_transaction(TransactionDraft(date(2026, 10, 2), "Synthetic", 1000, "Food"))
    budget = BudgetSettings(bills=(Bill("Food", 1000, ("Food",)), Bill("Rent", 2000, ("Rent",))))
    database.save_budget_settings(budget)
    with pytest.raises(ValueError, match="two bills"):
        save_category(database, config, "Rent", "Fixed", source="Food")
    assert database.list_transactions()[0]["category"] == "Food"
    assert database.get_budget_settings() == budget
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
    assert category_history(database, updated, TODAY).category_for("Zzz", "Mixed store") is None
    database.add_transaction(
        TransactionDraft(date(2026, 10, 5), "Another", 1000, "Food", merchant="Food store")
    )
    database.add_transaction(
        TransactionDraft(date(2026, 10, 6), "Another 2", 1000, "Food", merchant="Food store")
    )
    learned = category_history(database, updated, TODAY)
    assert learned.category_for("Zzz", "Food store") == "Food"


def test_merchant_history_auto_detects_categories_during_import(database):
    config = AppConfig()
    for day in (1, 2, 3):
        database.add_transaction(
            TransactionDraft(
                date(2026, 10, day), "Synthetic", 1000, "Food", merchant="Green Grocer"
            )
        )
    preview = preview_csv(
        b"Description,Date,Amount,Category,Merchant\nOther,2026-10-10,9.99,Surprise,Green Grocer\n",
        config,
        suggest=category_history(database, config, TODAY).category_for,
    )
    assert preview.valid_drafts[0].category == "Food"


def test_rules_beat_what_was_learned_which_beats_built_in_words(database):
    config = AppConfig(category_rules=(("coffee beans", "Food"),))

    def suggest(description, merchant=""):
        found = suggest_category(database, config, description, merchant, "expense", TODAY)
        return found.category, found.source

    assert suggest("Coffee beans", "Coffee shop") == ("Food", "rule")
    assert suggest("coffee") == ("Dining Out", "built-in")
    assert suggest("unmatched synthetic") == ("Uncategorized", "none")
    for day, category in ((1, "Food"), (2, "Tech")):
        database.add_transaction(
            TransactionDraft(date(2026, 10, day), "Coffee machine", 1000, category)
        )
    # Entries of its own say it is unclear, so the built-in word does not decide.
    assert suggest("coffee") == ("Uncategorized", "none")
    for day in (3, 4, 5, 6):
        database.add_transaction(TransactionDraft(date(2026, 10, day), "Coffee pods", 1000, "Food"))
    assert suggest("Coffee pods refill") == ("Food", "words")
    assert suggest("Coffee beans machine") == ("Food", "rule")


def test_keyword_rules_can_be_listed_removed_and_restored(database):
    from expense_analysis.categories import delete_keyword_rules, keyword_rules

    config = AppConfig(category_rules=(("cafe", "Dining Out"),))
    save_category(database, config, "Hobbies", "Personal", keyword="Craft")
    listed = {(r["keyword"], r["source"]) for r in keyword_rules(database, config)}
    assert listed == {("cafe", "config.toml"), ("craft", "Settings")}
    delete_keyword_rules(database, ["cafe", "craft"])
    updated = effective_config(database, config)
    assert updated.category_for("Campus cafe") == "Uncategorized"
    assert updated.category_for("craft paper") == "Uncategorized"
    assert keyword_rules(database, config) == []
    save_category(database, config, "Hobbies", "Personal", source="Hobbies", keyword="craft")
    assert effective_config(database, config).category_for("craft paper") == "Hobbies"
