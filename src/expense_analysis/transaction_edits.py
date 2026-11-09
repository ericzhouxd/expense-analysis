"""Validated table changes with atomic saves and stale-record protection."""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date

from .database import Database, DuplicateTransactionError
from .models import TransactionDraft


@dataclass(frozen=True)
class TransactionChange:
    transaction_id: str
    before: TransactionDraft
    after: TransactionDraft | None


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
