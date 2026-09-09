from datetime import date

import pytest

from expense_analysis.database import Database, DuplicateTransactionError
from expense_analysis.models import TransactionDraft


@pytest.fixture
def database(tmp_path):
    instance = Database(tmp_path / "expenses.sqlite3")
    instance.initialize()
    return instance


@pytest.fixture
def draft():
    return TransactionDraft(
        transaction_date=date(2026, 7, 30),
        description="Groceries",
        amount_cents=4288,
        category="Food",
        account="Checking",
        payment_method="Card",
    )


def test_add_update_and_delete_transaction(database, draft):
    transaction_id = database.add_transaction(draft)
    assert database.get_transaction(transaction_id)["description"] == "Groceries"
    assert database.get_transaction("missing") is None
    rows = database.list_transactions()
    assert len(rows) == 1
    assert rows[0]["id"] == transaction_id
    assert rows[0]["amount_cents"] == 4288
    assert database.list_transaction_categories() == ["Food"]

    changed = TransactionDraft(
        transaction_date=draft.transaction_date,
        description="Weekly groceries",
        amount_cents=4500,
        category=draft.category,
        account=draft.account,
        payment_method=draft.payment_method,
    )
    database.update_transaction(transaction_id, changed)
    assert database.list_transactions()[0]["description"] == "Weekly groceries"

    assert database.delete_transactions([transaction_id]) == 1
    assert database.count_transactions() == 0


def test_duplicate_is_rejected_by_default(database, draft):
    database.add_transaction(draft)
    with pytest.raises(DuplicateTransactionError):
        database.add_transaction(draft)


def test_bulk_import_skips_duplicate(database, draft):
    result = database.import_transactions([draft, draft])
    assert result.imported == 1
    assert result.duplicates_skipped == 1


def test_budget_upsert(database):
    database.set_budget("2026-07", "Food", 30000)
    database.set_budget("2026-07", "Food", 35000)
    budgets = database.get_budgets("2026-07")
    assert budgets == [{"month": "2026-07", "category": "Food", "amount_cents": 35000}]


def test_transaction_search(database, draft):
    database.add_transaction(draft)
    assert len(database.list_transactions(search="grocer")) == 1
    assert database.list_transactions(search="airfare") == []
