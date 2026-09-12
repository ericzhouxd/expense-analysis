from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .analytics import period_metrics, savings_summary, transactions_frame
from .config import OUTPUT_DIR, load_config
from .database import Database, DuplicateTransactionError
from .import_export import export_csv, preview_csv
from .models import TransactionDraft, format_dollars, parse_amount_cents, parse_date


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def add_main() -> None:
    parser = argparse.ArgumentParser(description="Add an expense to the local database.")
    parser.add_argument("--description")
    parser.add_argument("--date", dest="transaction_date")
    parser.add_argument("--amount")
    parser.add_argument("--category")
    parser.add_argument("--account")
    parser.add_argument("--method")
    parser.add_argument("--merchant", default="")
    parser.add_argument(
        "--type",
        dest="transaction_type",
        choices=("expense", "refund", "income", "transfer"),
        default="expense",
    )
    parser.add_argument("--notes", default="")
    arguments = parser.parse_args()

    config = load_config()
    database = Database()
    database.initialize()

    try:
        description = arguments.description or _prompt("Description")
        transaction_date = parse_date(
            arguments.transaction_date or _prompt("Date", date.today().isoformat())
        )
        amount_cents = abs(parse_amount_cents(arguments.amount or _prompt("Amount")))
        category = arguments.category or _prompt("Category", "Uncategorized")
        if category not in config.categories:
            print(f"Unknown category {category!r}; storing it as Uncategorized.")
            category = "Uncategorized"
        account = arguments.account or _prompt("Account", config.default_account)
        method = arguments.method or _prompt("Payment method", config.default_payment_method)
        draft = TransactionDraft(
            transaction_date=transaction_date,
            description=description,
            amount_cents=amount_cents,
            category=category,
            account=account,
            payment_method=method,
            merchant=arguments.merchant,
            transaction_type=arguments.transaction_type,
            notes=arguments.notes,
        )
        database.add_transaction(draft)
    except (ValueError, DuplicateTransactionError) as exc:
        parser.error(str(exc))
    print(f"Saved {format_dollars(amount_cents)} locally.")


def analyze_main() -> None:
    database = Database()
    database.initialize()
    config = load_config()
    rows = database.list_transactions()
    frame = transactions_frame(rows, config)
    if frame.empty:
        print("No transactions yet.")
        return

    metrics = period_metrics(frame, personal_only=True)
    savings = savings_summary(frame)
    partial = " (partial)" if metrics.is_partial else ""
    print(f"{metrics.period_label}{partial}")
    print(f"  Spending:          ${metrics.spending:,.2f}")
    print(f"  Projected:         ${metrics.projected_month_end:,.2f}")
    print(f"  Monthly average:   ${metrics.monthly_average:,.2f}")
    if metrics.change_from_previous is not None:
        print(f"  vs previous month: {metrics.change_from_previous:+.1f}%")
    income = float(savings["income"] or 0.0)
    if income:
        print(f"  Recorded income:   ${income:,.2f}")
        print(f"  Savings:           ${float(savings['savings'] or 0.0):,.2f}")


def import_main() -> None:
    parser = argparse.ArgumentParser(description="Import a CSV into the local database.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--yes", action="store_true", help="Import without prompting.")
    arguments = parser.parse_args()

    if not arguments.path.exists():
        parser.error(f"CSV does not exist: {arguments.path}")
    database = Database()
    database.initialize()
    preview = preview_csv(
        arguments.path.read_bytes(),
        load_config(),
        database.existing_fingerprints(),
    )
    print(
        f"{len(preview.valid_drafts)} ready, "
        f"{preview.duplicate_count} duplicates, {preview.invalid_count} invalid."
    )
    if preview.invalid_count:
        for row in preview.rows:
            if row.errors:
                print(f"  Row {row.row_number}: {'; '.join(row.errors)}")
    if not preview.valid_drafts:
        return
    if not arguments.yes and input("Import valid rows? [y/N]: ").strip().lower() != "y":
        print("Cancelled.")
        return
    result = database.import_transactions(preview.valid_drafts)
    print(f"Imported {result.imported}; skipped {result.duplicates_skipped} duplicates.")


def export_main() -> None:
    parser = argparse.ArgumentParser(description="Export local transactions to CSV.")
    parser.add_argument("path", nargs="?", type=Path, default=OUTPUT_DIR / "expenses_export.csv")
    arguments = parser.parse_args()

    database = Database()
    database.initialize()
    arguments.path.parent.mkdir(parents=True, exist_ok=True)
    arguments.path.write_bytes(export_csv(database.list_transactions()))
    print(f"Exported locally to {arguments.path}")


if __name__ == "__main__":
    analyze_main()
    sys.exit(0)
