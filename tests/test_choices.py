from datetime import date

import pytest

from expense_analysis.choices import choice_options
from expense_analysis.config import AppConfig
from expense_analysis.database import Database
from expense_analysis.models import TransactionDraft
from expense_analysis.term_budget import Bill, BudgetSettings


def test_saved_choices_are_shared_and_deduplicated(tmp_path):
    database = Database(tmp_path / "choices.sqlite3")
    database.initialize()
    config = AppConfig()
    database.add_transaction(
        TransactionDraft(
            date(2026, 9, 10),
            "Synthetic entry",
            1000,
            "Food",
            account="Travel wallet",
            payment_method="Gift card",
        )
    )
    database.save_budget_settings(
        BudgetSettings(bills=(Bill("Studio", 1000, ("Art, materials",)),))
    )

    categories = choice_options(database, config, "category")
    assert [value for value in categories if value.casefold() == "food"] == ["Food"]
    assert "Art, materials" in categories
    assert "Travel wallet" in choice_options(database, config, "account")
    assert "Gift card" in choice_options(database, config, "payment_method")
    assert "" not in choice_options(database, config, "account")
    with pytest.raises(ValueError, match="fixed choices"):
        choice_options(database, config, "transaction_type")


def test_choice_options_fall_back_for_proxies_without_a_distinct_query(tmp_path):
    class Proxy:
        def __init__(self, database):
            self._database = database

        def list_transactions(self):
            return self._database.list_transactions()

        def get_budget_settings(self):
            return self._database.get_budget_settings()

    database = Database(tmp_path / "proxy.sqlite3")
    database.initialize()
    database.add_transaction(
        TransactionDraft(
            date(2026, 9, 10),
            "Synthetic entry",
            1000,
            "Food",
            account="Travel wallet",
            payment_method="Gift card",
        )
    )
    options = choice_options(Proxy(database), AppConfig(), "account")  # type: ignore[arg-type]
    assert "Travel wallet" in options


def test_remove_unused_choices_persists_and_protects_references(tmp_path):
    from expense_analysis.categories import effective_config, save_category
    from expense_analysis.choices import remove_unused_choices, unused_choices

    database = Database(tmp_path / "cleanup.sqlite3")
    database.initialize()
    config = AppConfig(category_rules=(("coffee", "Dining Out"),))
    database.add_transaction(TransactionDraft(date(2026, 9, 1), "Synthetic", 100, "Food"))
    for kind, name in (("category", "Tech"), ("account", "Cash"), ("payment_method", "Online")):
        assert name in unused_choices(database, config, kind)
        remove_unused_choices(database, config, kind, [name])
        assert name not in choice_options(database, config, kind)
        assert name not in choice_options(database, effective_config(database, config), kind)
    for kind, name in (
        ("category", "Food"),
        ("category", "Dining Out"),
        ("category", "Uncategorized"),
        ("account", "Checking"),
        ("payment_method", "Apple Pay"),
    ):
        with pytest.raises(ValueError, match="in use"):
            remove_unused_choices(database, config, kind, [name])
    save_category(database, config, "Tech", "Personal")
    assert "Tech" in effective_config(database, config).categories


@pytest.mark.parametrize(
    "kind,original,new",
    [
        ("account", "Checking", "Daily account"),
        ("payment_method", "Apple Pay", "Mobile wallet"),
    ],
)
def test_rename_and_delete_used_choice_preserves_transactions_and_defaults(
    tmp_path, kind, original, new
):
    from dataclasses import replace

    from expense_analysis.categories import effective_config
    from expense_analysis.choices import delete_choice, save_choice

    db = Database(tmp_path / "rename.sqlite")
    db.initialize()
    config = AppConfig()
    draft = TransactionDraft(
        date(2026, 10, 1), "Synthetic", 1200, "Food", account="Checking", payment_method="Apple Pay"
    )
    identifier = db.add_transaction(draft)
    assert save_choice(db, config, kind, new, source=original) == 1
    saved = db.get_transaction(identifier)
    assert saved is not None
    assert saved[kind] == new
    assert saved["fingerprint"] == replace(draft, **{kind: new}).fingerprint
    assert original not in choice_options(db, config, kind)
    assert getattr(effective_config(db, config), f"default_{kind}") == new
    with pytest.raises(ValueError, match="in use"):
        delete_choice(db, config, kind, new)
    save_choice(db, config, kind, "Replacement")
    delete_choice(db, config, kind, new, replacement="Replacement")
    db.initialize()
    assert db.count_transactions() == 1
    saved = db.get_transaction(identifier)
    assert saved is not None
    assert saved[kind] == "Replacement"
    assert getattr(effective_config(db, config), f"default_{kind}") == "Replacement"
    assert new not in choice_options(db, config, kind)
    assert original not in choice_options(db, config, kind)
    # Renamed configured values must stay removed even after deleting their unused target.
    save_choice(db, config, kind, "Unused")
    delete_choice(db, config, kind, "Unused")
    assert "Unused" not in choice_options(db, config, kind)


def test_category_delete_remaps_history_rules_plan_and_treatment(tmp_path):
    from expense_analysis.categories import effective_config
    from expense_analysis.choices import delete_choice

    db = Database(tmp_path / "category-delete.sqlite")
    db.initialize()
    config = AppConfig(category_rules=(("grocer", "Food"),))
    identifier = db.add_transaction(TransactionDraft(date(2026, 10, 1), "Synthetic", 1000, "Food"))
    db.save_budget_settings(BudgetSettings(bills=(Bill("Food bill", 1000, ("Food",)),)))
    db.save_spending_rules({"categories": {"Food": "Irregular"}})
    delete_choice(db, config, "category", "Food", replacement="Dining Out")
    saved = db.get_transaction(identifier)
    assert saved is not None
    assert saved["category"] == "Dining Out"
    assert "Food" not in choice_options(db, config, "category")
    saved_budget = db.get_budget_settings()
    assert saved_budget is not None
    assert saved_budget.bills[0].categories == ("Dining Out",)
    assert effective_config(db, config).category_for("grocer") == "Dining Out"
    assert db.get_spending_rules()["categories"] == {"Dining Out": "Irregular"}


def test_budget_only_category_can_be_renamed_and_unused_treatment_removed(tmp_path):
    from expense_analysis.categories import save_category
    from expense_analysis.choices import delete_choice

    db = Database(tmp_path / "budget-only.sqlite")
    db.initialize()
    config = AppConfig()
    db.save_budget_settings(BudgetSettings(bills=(Bill("Club dues", 1000, ("New category",)),)))
    save_category(db, config, "Renamed", "Fixed", source="New category")
    saved_budget = db.get_budget_settings()
    assert saved_budget is not None
    assert saved_budget.bills[0].categories == ("Renamed",)
    save_category(db, config, "Unused", "Personal")
    db.save_spending_rules({"categories": {"Unused": "Everyday"}})
    delete_choice(db, config, "category", "Unused")
    assert "Unused" not in db.get_spending_rules()["categories"]
    assert "Unused" not in choice_options(db, config, "category")


def test_delete_rechecks_usage_before_removing(tmp_path):
    from expense_analysis.choices import delete_choice

    db = Database(tmp_path / "inline.sqlite")
    db.initialize()
    # A stale client may think a choice is unused; the server checks again before deleting.
    db.add_transaction(TransactionDraft(date(2026, 10, 1), "New synthetic", 500, "Tech"))
    with pytest.raises(ValueError, match="in use"):
        delete_choice(db, AppConfig(), "category", "Tech")


def test_restore_choice_undoes_an_unused_removal(tmp_path):
    from expense_analysis.categories import effective_config, save_category
    from expense_analysis.choices import remove_unused_choices, restore_choice

    db = Database(tmp_path / "restore.sqlite3")
    db.initialize()
    config = AppConfig()
    save_category(db, config, "Hobbies", "Fixed")
    remove_unused_choices(db, config, "category", ["Hobbies"])
    remove_unused_choices(db, config, "account", ["Cash"])
    assert "Hobbies" not in choice_options(db, config, "category")
    restore_choice(db, "category", "Hobbies", "Fixed")
    restore_choice(db, "account", "Cash")
    assert "Hobbies" in choice_options(db, config, "category")
    assert effective_config(db, config).spending_class("Hobbies") == "Fixed"
    assert "Cash" in choice_options(db, config, "account")
