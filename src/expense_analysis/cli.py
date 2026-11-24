from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .analytics import period_metrics, savings_summary, transactions_frame
from .categories import category_history, effective_config, suggest_category
from .coa_outlook import coa_outlook
from .config import OUTPUT_DIR, TRANSACTION_TYPES, AppConfig, load_config
from .database import Database, DuplicateTransactionError
from .import_export import CsvDecodeError, export_csv, preview_csv
from .models import TransactionDraft, format_dollars, parse_amount_cents, validate_transaction_date
from .replay import smart_budget
from .spending_summary import spending_summary
from .spending_treatment import classify_spending
from .term_budget import term_budget


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _local_setup() -> tuple[Database, AppConfig]:
    """Open the ledger with the same categories, accounts and rules as the app."""
    database = Database()
    database.initialize()
    return database, effective_config(database, load_config())


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
        choices=TRANSACTION_TYPES,
    )
    parser.add_argument("--notes", default="")
    arguments = parser.parse_args()

    database, config = _local_setup()

    try:
        description = arguments.description or _prompt("Description")
        transaction_date = validate_transaction_date(
            arguments.transaction_date or _prompt("Date", date.today().isoformat())
        )
        amount_cents = abs(parse_amount_cents(arguments.amount or _prompt("Amount")))
        transaction_type = arguments.transaction_type or config.default_transaction_type
        requested = arguments.category or _prompt(
            "Category",
            suggest_category(
                database,
                config,
                description,
                arguments.merchant,
                transaction_type,
                date.today(),
            ).category,
        )
        category = config.category_for("", provided=requested)
        if category == "Uncategorized" and requested.strip().casefold() != "uncategorized":
            print(f"Unknown category {requested!r}; storing it as Uncategorized.")
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
            transaction_type=transaction_type,
            notes=arguments.notes,
        )
        database.add_transaction(draft)
    except (ValueError, DuplicateTransactionError) as exc:
        parser.error(str(exc))
    print(f"Saved {format_dollars(amount_cents)} locally.")


def analyze_main() -> None:
    database, config = _local_setup()
    rows = database.list_transactions()
    today = date.today()
    smart = smart_budget(
        database.get_budget_settings(),
        database.get_spending_rules(),
        rows,
        today,
        config.fixed_categories,
    )
    budget, rules = smart.auto.settings, smart.auto.rules
    frame = transactions_frame(classify_spending(rows, budget, rules), config)
    if frame.empty:
        print("No transactions yet.")
        return

    metrics = period_metrics(frame[frame["spending_treatment"].eq("Everyday")], today)
    summary = spending_summary(budget, rows, today, rules)
    week = term_budget(budget, rows, today, rules, lines=smart.lines)["week"]
    savings = savings_summary(frame)
    partial = " (partial)" if metrics.is_partial else ""
    print(f"{metrics.period_label}{partial}")
    print(f"  Everyday spending: ${metrics.spending:,.2f}")
    print(f"  Projected:         ${metrics.projected_month_end:,.2f}")
    print(f"  Monthly average:   ${metrics.monthly_average:,.2f}")
    change = summary["everyday_month_comparison"]["percent"]
    if change is not None:
        print(f"  vs same days last month: {change:+.1f}%")
    if week is not None:
        left, line = format_dollars(week["left"]), format_dollars(week["line"])
        print(f"  {week['label']}: {left} left of {line}")
    coa = coa_outlook(budget, rows, today, rules, smart.auto.habits)
    if coa["ready"]:
        margin = coa["margin"]
        print(
            f"  School year:       {format_dollars(coa['projected'])} expected of "
            f"{coa['school']}'s {format_dollars(coa['line'])} "
            f"({format_dollars(abs(margin))} {'under' if margin >= 0 else 'over'})"
        )
    income = float(savings["income"] or 0.0)
    if income:
        print(f"  Recorded income:   ${income:,.2f}")
        print(f"  Savings:           ${float(savings['savings'] or 0.0):,.2f}")


def import_main() -> None:
    parser = argparse.ArgumentParser(description="Import a CSV into the local database.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--yes", action="store_true", help="Import without prompting.")
    parser.add_argument(
        "--negative-expenses",
        choices=("refund", "income"),
        help="Bank-style signs: negative amounts are expenses and positive amounts are "
        "refunds or income. Rows with a Type column keep their type.",
    )
    arguments = parser.parse_args()

    if not arguments.path.exists():
        parser.error(f"CSV does not exist: {arguments.path}")
    database, config = _local_setup()
    try:
        preview = preview_csv(
            arguments.path.read_bytes(),
            config,
            database.existing_fingerprints(),
            suggest=category_history(database, config, date.today()).category_for,
            sign_convention=(
                f"negative_expense_{arguments.negative_expenses}"
                if arguments.negative_expenses
                else "positive_expense"
            ),
        )
    except CsvDecodeError as exc:
        print(f"Cannot read {arguments.path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
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
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=OUTPUT_DIR / f"expenses-{date.today().isoformat()}.csv",
        help="Destination file (default: a dated file in output/, so backups accumulate).",
    )
    arguments = parser.parse_args()

    database = Database()
    database.initialize()
    arguments.path.parent.mkdir(parents=True, exist_ok=True)
    arguments.path.write_bytes(export_csv(database.list_transactions()))
    print(f"Exported locally to {arguments.path}")


if __name__ == "__main__":
    analyze_main()
    sys.exit(0)
