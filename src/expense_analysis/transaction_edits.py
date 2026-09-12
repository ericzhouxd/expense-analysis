"""Validated table changes with atomic saves and stale-record protection."""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from decimal import InvalidOperation

import pandas as pd

from .database import Database, DuplicateTransactionError
from .models import TransactionDraft, parse_amount_cents, parse_date


@dataclass(frozen=True)
class TransactionChange:
    transaction_id: str
    before: TransactionDraft
    after: TransactionDraft | None


def draft_from_editor(row: pd.Series) -> TransactionDraft:
    def text(column: str, required: bool = False) -> str:
        raw = row[column]
        if isinstance(raw, list):
            if len(raw) > 1:
                raise ValueError(f"Choose only one {column.lower()}; remove the previous choice")
            raw = raw[0] if raw else ""
        value = "" if pd.isna(raw) else str(raw).strip()
        if required and not value:
            raise ValueError(f"{column} is required")
        return value

    raw_date = row["Date"]
    if pd.isna(raw_date) or (isinstance(raw_date, str) and not raw_date.strip()):
        raise ValueError("Date is required")
    try:
        transaction_date = parse_date(raw_date)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    try:
        amount = parse_amount_cents(row["Amount"])
    except (ValueError, OverflowError, InvalidOperation) as exc:
        raise ValueError("Amount must be a finite positive number") from exc
    return TransactionDraft(
        transaction_date=transaction_date,
        description=text("Description", required=True),
        amount_cents=amount,
        category=text("Category", required=True),
        account=text("Account"),
        payment_method=text("Payment method"),
        merchant=text("Merchant"),
        transaction_type=text("Type", required=True),
        notes=text("Notes"),
    ).validated()


def collect_changes(original: pd.DataFrame, edited: pd.DataFrame) -> list[TransactionChange]:
    if edited["ID"].duplicated().any() or set(original["ID"]) != set(edited["ID"]):
        raise ValueError("The table records changed. Discard edits and reload the table.")
    baseline = original.set_index("ID")
    changes = []
    for row_number, (_, row) in enumerate(edited.iterrows(), start=1):
        before_row = baseline.loc[row["ID"]]
        if not row["Delete"] and row.drop(labels=["ID", "Delete"]).equals(
            before_row.drop(labels="Delete")
        ):
            continue
        try:
            before = draft_from_editor(before_row)
            after = None if row["Delete"] else draft_from_editor(row)
        except ValueError as exc:
            raise ValueError(f"Row {row_number}: {exc}") from exc
        if before != after:
            changes.append(TransactionChange(str(row["ID"]), before, after))
    return changes


def apply_changes(database: Database, changes: list[TransactionChange]) -> None:
    """Validate the entire batch before writing; conflicts roll back every change."""
    if not changes:
        return
    if len({change.transaction_id for change in changes}) != len(changes):
        raise ValueError("A transaction appears more than once in this batch")
    validated_after = {
        change.transaction_id: (change.after.validated() if change.after is not None else None)
        for change in changes
    }
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for change in changes:
            row = connection.execute(
                "SELECT * FROM transactions WHERE id = ?", (change.transaction_id,)
            ).fetchone()
            if row is None:
                raise ValueError("A transaction was deleted elsewhere. Discard edits and reload.")
            stored = {key: row[key] for key in asdict(change.before)}
            stored["transaction_date"] = date.fromisoformat(stored["transaction_date"])
            if TransactionDraft(**stored).validated() != change.before:
                raise ValueError("A transaction changed elsewhere. Discard edits and reload.")

        # Check the final batch state, including edits that would collide with each other.
        fingerprints = Counter(
            row["fingerprint"] for row in connection.execute("SELECT fingerprint FROM transactions")
        )
        original_counts = fingerprints.copy()
        for change in changes:
            fingerprints[change.before.fingerprint] -= 1
        for change in changes:
            draft = validated_after[change.transaction_id]
            if draft is not None:
                fingerprints[draft.fingerprint] += 1
        if any(count > max(1, original_counts[key]) for key, count in fingerprints.items()):
            raise DuplicateTransactionError("These edits would create a duplicate transaction")

        for change in changes:
            draft = validated_after[change.transaction_id]
            if draft is None:
                connection.execute(
                    "DELETE FROM transactions WHERE id = ?", (change.transaction_id,)
                )
            else:
                values = asdict(draft)
                values["transaction_date"] = values["transaction_date"].isoformat()
                values["fingerprint"] = draft.fingerprint
                assignments = ", ".join(f"{column} = ?" for column in values)
                connection.execute(
                    f"UPDATE transactions SET {assignments}, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (*values.values(), change.transaction_id),
                )
