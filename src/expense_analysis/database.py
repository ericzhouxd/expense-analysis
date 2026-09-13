from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import DATABASE_PATH, ensure_local_directories
from .models import TransactionDraft, new_transaction_id
from .spending_plan import SpendingPlan

CHOICE_COLUMNS = frozenset({"category", "account", "payment_method"})


class DuplicateTransactionError(ValueError):
    """Raised when an identical transaction already exists."""


@dataclass(frozen=True)
class ImportResult:
    imported: int
    duplicates_skipped: int


class Database:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        ensure_local_directories()
        with self.connect() as connection:
            # WAL is persistent database state; configure it once during startup
            # instead of issuing the pragma for every short-lived connection.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    transaction_date TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                    category TEXT NOT NULL DEFAULT 'Uncategorized',
                    account TEXT NOT NULL DEFAULT '',
                    payment_method TEXT NOT NULL DEFAULT '',
                    merchant TEXT NOT NULL DEFAULT '',
                    transaction_type TEXT NOT NULL
                        CHECK (transaction_type IN ('expense', 'refund', 'income', 'transfer')),
                    notes TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_transactions_date
                    ON transactions(transaction_date);
                CREATE INDEX IF NOT EXISTS idx_transactions_category
                    ON transactions(category);
                CREATE INDEX IF NOT EXISTS idx_transactions_fingerprint
                    ON transactions(fingerprint);

                CREATE TABLE IF NOT EXISTS spending_plans (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version < 3:
                # Schema 3 drops `budgets`. `spending_plans` superseded its monthly
                # category rows, so nothing has read or written it since.
                connection.execute("DROP TABLE IF EXISTS budgets")
                connection.execute("PRAGMA user_version = 3")

    def get_spending_plan(self) -> SpendingPlan | None:
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM spending_plans WHERE id = 1").fetchone()
        return SpendingPlan.from_dict(json.loads(row["payload"])) if row else None

    def save_spending_plan(self, plan: SpendingPlan) -> None:
        payload = json.dumps(plan.to_dict(), ensure_ascii=False)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO spending_plans (id, payload) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload,
                updated_at = CURRENT_TIMESTAMP""",
                (payload,),
            )

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        draft: TransactionDraft,
        *,
        allow_duplicate: bool,
    ) -> str | None:
        clean = draft.validated()
        if not allow_duplicate:
            duplicate = connection.execute(
                "SELECT id FROM transactions WHERE fingerprint = ? LIMIT 1",
                (clean.fingerprint,),
            ).fetchone()
            if duplicate:
                return None

        transaction_id = new_transaction_id()
        connection.execute(
            """
            INSERT INTO transactions (
                id, transaction_date, description, amount_cents, category, account,
                payment_method, merchant, transaction_type, notes, fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                clean.transaction_date.isoformat(),
                clean.description,
                clean.amount_cents,
                clean.category,
                clean.account,
                clean.payment_method,
                clean.merchant,
                clean.transaction_type,
                clean.notes,
                clean.fingerprint,
            ),
        )
        return transaction_id

    def add_transaction(self, draft: TransactionDraft, *, allow_duplicate: bool = False) -> str:
        with self.connect() as connection:
            transaction_id = self._insert(connection, draft, allow_duplicate=allow_duplicate)
        if transaction_id is None:
            raise DuplicateTransactionError("An identical transaction already exists")
        return transaction_id

    def import_transactions(
        self,
        drafts: Iterable[TransactionDraft],
        *,
        allow_duplicates: bool = False,
    ) -> ImportResult:
        imported = 0
        duplicates = 0
        with self.connect() as connection:
            for draft in drafts:
                transaction_id = self._insert(connection, draft, allow_duplicate=allow_duplicates)
                if transaction_id is None:
                    duplicates += 1
                else:
                    imported += 1
        return ImportResult(imported=imported, duplicates_skipped=duplicates)

    def update_transaction(self, transaction_id: str, draft: TransactionDraft) -> None:
        clean = draft.validated()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE transactions SET
                    transaction_date = ?,
                    description = ?,
                    amount_cents = ?,
                    category = ?,
                    account = ?,
                    payment_method = ?,
                    merchant = ?,
                    transaction_type = ?,
                    notes = ?,
                    fingerprint = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    clean.transaction_date.isoformat(),
                    clean.description,
                    clean.amount_cents,
                    clean.category,
                    clean.account,
                    clean.payment_method,
                    clean.merchant,
                    clean.transaction_type,
                    clean.notes,
                    clean.fingerprint,
                    transaction_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown transaction: {transaction_id}")

    def delete_transactions(self, transaction_ids: Sequence[str]) -> int:
        ids = [transaction_id for transaction_id in transaction_ids if transaction_id]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM transactions WHERE id IN ({placeholders})", ids
            )
        return cursor.rowcount

    def list_transactions(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        categories: Sequence[str] = (),
        transaction_types: Sequence[str] = (),
        accounts: Sequence[str] = (),
        search: str = "",
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        parameters: list[object] = []

        if start:
            clauses.append("transaction_date >= ?")
            parameters.append(start.isoformat())
        if end:
            clauses.append("transaction_date <= ?")
            parameters.append(end.isoformat())
        if search.strip():
            clauses.append(
                "(description LIKE ? OR merchant LIKE ? OR notes LIKE ? OR category LIKE ?)"
            )
            search_pattern = f"%{search.strip()}%"
            parameters.extend([search_pattern] * 4)
        for column, values in (
            ("category", categories),
            ("transaction_type", transaction_types),
            ("account", accounts),
        ):
            if values:
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{column} IN ({placeholders})")
                parameters.extend(values)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, transaction_date, description, amount_cents, category,
                       account, payment_method, merchant, transaction_type, notes,
                       fingerprint, created_at, updated_at
                FROM transactions
                {where}
                ORDER BY transaction_date DESC, created_at DESC
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_transaction(self, transaction_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, transaction_date, description, amount_cents, category,
                       account, payment_method, merchant, transaction_type, notes,
                       fingerprint, created_at, updated_at
                FROM transactions
                WHERE id = ?
                """,
                (transaction_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_choice_values(self, kind: str) -> list[str]:
        """Return distinct saved values for an editable choice column."""
        if kind not in CHOICE_COLUMNS:
            raise ValueError("This field uses fixed choices")
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT {kind}
                FROM transactions
                WHERE trim({kind}) != ''
                ORDER BY {kind} COLLATE NOCASE
                """
            ).fetchall()
        return [str(row[kind]) for row in rows]

    def list_transaction_categories(self) -> list[str]:
        return self.list_choice_values("category")

    def existing_fingerprints(self) -> set[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT DISTINCT fingerprint FROM transactions").fetchall()
        return {str(row["fingerprint"]) for row in rows}

    def duplicate_groups(self) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT fingerprint, COUNT(*) AS duplicate_count,
                       GROUP_CONCAT(id) AS transaction_ids
                FROM transactions
                GROUP BY fingerprint
                HAVING COUNT(*) > 1
                ORDER BY duplicate_count DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def count_transactions(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS transaction_count FROM transactions"
            ).fetchone()
        return int(row["transaction_count"])
