import sqlite3
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from expense_analysis.database import Database, DuplicateTransactionError
from expense_analysis.models import TransactionDraft
from expense_analysis.transaction_edits import (
    TransactionChange,
    apply_changes,
    collect_changes,
    draft_from_editor,
)


@pytest.fixture
def ledger(tmp_path):
    database = Database(tmp_path / "edits.sqlite3")
    database.initialize()
    first = TransactionDraft(date(2026, 9, 1), "Synthetic lunch", 1250, "Food")
    second = replace(first, description="Synthetic train", category="Transportation")
    return database, [(database.add_transaction(draft), draft) for draft in (first, second)]


def editor_row(identifier, draft):
    return {
        "ID": identifier,
        "Delete": False,
        "Date": draft.transaction_date,
        "Description": draft.description,
        "Amount": draft.amount_cents / 100,
        "Category": draft.category,
        "Account": draft.account,
        "Payment method": draft.payment_method,
        "Merchant": draft.merchant,
        "Type": draft.transaction_type,
        "Notes": draft.notes,
    }


@pytest.mark.parametrize("amount", [-1, 0, None, float("nan"), float("inf"), "invalid"])
def test_invalid_amount_is_rejected_without_sign_conversion(ledger, amount):
    _, [(identifier, draft), _] = ledger
    row = editor_row(identifier, draft)
    row["Amount"] = amount
    with pytest.raises(ValueError):
        draft_from_editor(pd.Series(row))


@pytest.mark.parametrize("field", ["Description", "Date", "Category", "Type"])
def test_missing_required_fields_are_rejected(ledger, field):
    _, [(identifier, draft), _] = ledger
    row = editor_row(identifier, draft)
    row[field] = None
    with pytest.raises(ValueError):
        draft_from_editor(pd.Series(row))


def test_only_changed_rows_are_saved_and_deletions_are_explicit(ledger):
    database, entries = ledger
    baseline = pd.DataFrame([editor_row(*entry) for entry in entries])
    assert collect_changes(baseline, baseline.copy()) == []
    edited = baseline.copy()
    edited.loc[0, "Notes"] = "Updated note"
    changes = collect_changes(baseline, edited)
    assert len(changes) == 1
    apply_changes(database, changes)
    assert database.get_transaction(entries[0][0])["notes"] == "Updated note"
    assert database.get_transaction(entries[1][0])["notes"] == ""
    edited = baseline.copy()
    edited.loc[1, "Delete"] = True
    apply_changes(database, collect_changes(baseline, edited))
    assert database.get_transaction(entries[1][0]) is None


def test_choice_cells_preserve_scalars_and_reject_multiple_values(ledger):
    _, entries = ledger
    original = pd.DataFrame([editor_row(*entry) for entry in entries])
    edited = original.copy(deep=True)
    for column in ("Category", "Account", "Payment method"):
        edited[column] = edited[column].map(lambda value: [value] if value else [])
    assert collect_changes(original, edited) == []
    edited.at[0, "Category"] = ["New category"]
    assert collect_changes(original, edited)[0].after.category == "New category"
    edited.at[0, "Account"] = ["Checking", "Savings"]
    with pytest.raises(ValueError, match="Row 1: Choose only one account"):
        collect_changes(original, edited)
    edited.at[0, "Account"] = []
    edited.at[0, "Category"] = []
    with pytest.raises(ValueError, match="Category is required"):
        collect_changes(original, edited)


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
def test_duplicate_detection_is_independent_of_batch_order(ledger, reverse):
    database, [(first_id, first), (second_id, second)] = ledger
    changes = [
        TransactionChange(first_id, first, replace(second, notes="Duplicate")),
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


def render_editor(database):
    from expense_analysis.analytics import transactions_frame
    from expense_analysis.config import AppConfig
    from expense_analysis.ui import _render_transactions

    config = AppConfig()
    _render_transactions(database, transactions_frame(database.list_transactions(), config), config)


def render_review(database, changes):
    from expense_analysis.ui import _review_transaction_changes

    _review_transaction_changes(database, changes)


def test_edit_table_starts_with_review_disabled_and_can_discard(ledger):
    database, _ = ledger
    app = AppTest.from_function(render_editor, args=(database,)).run()
    app.session_state["transaction_view"] = "Edit table"
    app.run()
    assert not app.exception
    assert next(b for b in app.button if b.label == "Review changes (0)").disabled
    generation = app.session_state["transaction_editor_generation"]
    next(b for b in app.button if b.label == "Discard edits / reload").click().run()
    assert app.session_state["transaction_editor_generation"] > generation
    assert database.count_transactions() == 2


def test_review_cannot_delete_without_acknowledgement(ledger):
    database, [(identifier, draft), _] = ledger
    app = AppTest.from_function(
        render_review, args=(database, [TransactionChange(identifier, draft, None)])
    ).run()
    assert next(b for b in app.button if b.label == "Confirm changes").disabled
    assert database.get_transaction(identifier) is not None
    app.checkbox[0].check().run()
    next(b for b in app.button if b.label == "Confirm changes").click().run()
    assert not app.exception
    assert database.get_transaction(identifier) is None
