from datetime import date

import pytest

from expense_analysis.choices import choice_options
from expense_analysis.config import AppConfig
from expense_analysis.database import Database
from expense_analysis.models import TransactionDraft
from expense_analysis.spending_plan import Commitment, SpendingPlan


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
    database.save_spending_plan(
        SpendingPlan(
            name="Synthetic plan",
            start=date(2026, 9, 1),
            months=9,
            academic_target_cents=10000,
            summer_target_cents=0,
            buffer_cents=0,
            commitments=(Commitment("Studio", 1000, ("Art, materials",)),),
            reference={},
        )
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

        def get_spending_plan(self):
            return self._database.get_spending_plan()

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
