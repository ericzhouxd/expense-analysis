import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from expense_analysis.database import Database, DuplicateTransactionError
from expense_analysis.models import TransactionDraft
from expense_analysis.transaction_edits import (
    TransactionChange,
    apply_changes,
)


@pytest.fixture
def ledger(tmp_path):
    database = Database(tmp_path / "edits.sqlite3")
    database.initialize()
    first = TransactionDraft(date(2026, 9, 1), "Synthetic lunch", 1250, "Food")
    second = replace(first, description="Synthetic train", category="Transportation")
    return database, [(database.add_transaction(draft), draft) for draft in (first, second)]


def test_stale_notes_block_the_whole_batch_including_deletions(ledger):
    database, [(first_id, first), (second_id, second)] = ledger
    database.update_transaction(second_id, replace(second, notes="Changed elsewhere"))
    with pytest.raises(ValueError, match="changed elsewhere"):
        apply_changes(
            database,
            [
                TransactionChange(first_id, first, None),
                TransactionChange(second_id, second, replace(second, amount_cents=2000)),
            ],
        )
    assert database.get_transaction(first_id) is not None
    assert database.get_transaction(second_id)["amount_cents"] == 1250


def test_mid_write_failure_rolls_back_earlier_changes(ledger):
    database, entries = ledger
    with database.connect() as connection:
        connection.execute("""
            CREATE TRIGGER reject_train BEFORE UPDATE ON transactions
            WHEN OLD.description = 'Synthetic train'
            BEGIN SELECT RAISE(ABORT, 'Synthetic failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError):
        apply_changes(
            database,
            [
                TransactionChange(identifier, draft, replace(draft, amount_cents=2000))
                for identifier, draft in entries
            ],
        )
    assert all(row["amount_cents"] == 1250 for row in database.list_transactions())


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("transaction_type", ["expense", "Expense"])
def test_duplicate_detection_is_independent_of_batch_order(ledger, reverse, transaction_type):
    database, [(first_id, first), (second_id, second)] = ledger
    changes = [
        TransactionChange(
            first_id, first, replace(second, notes="Duplicate", transaction_type=transaction_type)
        ),
        TransactionChange(second_id, second, replace(second, notes="Note only")),
    ]
    with pytest.raises(DuplicateTransactionError):
        apply_changes(database, changes[::-1] if reverse else changes)
    assert database.get_transaction(first_id)["description"] == first.description


def test_unvalidated_type_persists_a_fingerprint_matching_the_stored_row(ledger):
    database, [(identifier, draft), _] = ledger
    updated = replace(draft, transaction_type="Expense", notes="Mixed case")
    assert updated.fingerprint != updated.validated().fingerprint
    apply_changes(database, [TransactionChange(identifier, draft, updated)])
    stored = database.get_transaction(identifier)
    assert stored["transaction_type"] == "expense"
    stored_draft = TransactionDraft(
        transaction_date=date.fromisoformat(stored["transaction_date"]),
        description=stored["description"],
        amount_cents=stored["amount_cents"],
        category=stored["category"],
        account=stored["account"],
        payment_method=stored["payment_method"],
        merchant=stored["merchant"],
        transaction_type=stored["transaction_type"],
        notes=stored["notes"],
    ).validated()
    assert stored["fingerprint"] == stored_draft.fingerprint
