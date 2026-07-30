from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .config import AppConfig
from .models import TransactionDraft, parse_amount_cents, parse_date


@dataclass(frozen=True)
class ImportRow:
    row_number: int
    draft: TransactionDraft | None
    errors: tuple[str, ...] = ()
    duplicate: bool = False


@dataclass(frozen=True)
class ImportPreview:
    rows: tuple[ImportRow, ...]

    @property
    def valid_drafts(self) -> list[TransactionDraft]:
        return [
            row.draft
            for row in self.rows
            if row.draft is not None and not row.errors and not row.duplicate
        ]

    @property
    def invalid_count(self) -> int:
        return sum(bool(row.errors) for row in self.rows)

    @property
    def duplicate_count(self) -> int:
        return sum(row.duplicate for row in self.rows)


def _value(row: dict[str, str], *names: str) -> str:
    normalized = {key.casefold().strip(): (value or "") for key, value in row.items()}
    for name in names:
        if name.casefold() in normalized:
            return normalized[name.casefold()].strip()
    return ""


def preview_csv(
    content: bytes,
    config: AppConfig,
    existing_fingerprints: set[str] | None = None,
) -> ImportPreview:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return ImportPreview((ImportRow(1, None, ("CSV header is missing",)),))

    known_fingerprints = set(existing_fingerprints or ())
    seen_in_file: set[str] = set()
    preview_rows: list[ImportRow] = []

    for row_number, row in enumerate(reader, start=2):
        errors: list[str] = []
        description = _value(row, "description", "expense")
        if description.startswith("---"):
            continue
        if not description:
            errors.append("Description is required")

        try:
            transaction_date = parse_date(_value(row, "date", "transaction_date"))
        except ValueError as exc:
            errors.append(str(exc))
            transaction_date = None

        try:
            signed_cents = parse_amount_cents(_value(row, "amount", "amount_dollars"))
            if signed_cents == 0:
                errors.append("Amount must not be zero")
        except ValueError as exc:
            errors.append(str(exc))
            signed_cents = 0

        transaction_type = _value(row, "type", "transaction_type").casefold()
        if not transaction_type:
            transaction_type = "refund" if signed_cents < 0 else "expense"

        original_category = _value(row, "category")
        notes = _value(row, "notes")
        merchant = _value(row, "merchant")
        category = config.category_for(description, merchant, original_category)
        if original_category and category == "Uncategorized":
            note = f"Imported category: {original_category}"
            notes = f"{notes}\n{note}".strip()

        draft: TransactionDraft | None = None
        if transaction_date is not None and description and signed_cents:
            try:
                draft = TransactionDraft(
                    transaction_date=transaction_date,
                    description=description,
                    amount_cents=abs(signed_cents),
                    category=category,
                    account=_value(row, "account", "from", "source"),
                    payment_method=_value(row, "payment_method", "method"),
                    merchant=merchant,
                    transaction_type=transaction_type,
                    notes=notes,
                ).validated()
            except ValueError as exc:
                errors.append(str(exc))

        duplicate = False
        if draft:
            duplicate = draft.fingerprint in known_fingerprints or draft.fingerprint in seen_in_file
            seen_in_file.add(draft.fingerprint)

        preview_rows.append(
            ImportRow(
                row_number=row_number,
                draft=draft,
                errors=tuple(errors),
                duplicate=duplicate,
            )
        )

    return ImportPreview(tuple(preview_rows))


def export_csv(rows: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    fieldnames = (
        "ID",
        "Date",
        "Description",
        "Amount",
        "Category",
        "Account",
        "Payment Method",
        "Merchant",
        "Type",
        "Notes",
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "ID": row["id"],
                "Date": row["transaction_date"],
                "Description": row["description"],
                "Amount": f"{int(row['amount_cents']) / 100:.2f}",
                "Category": row["category"],
                "Account": row["account"],
                "Payment Method": row["payment_method"],
                "Merchant": row["merchant"],
                "Type": row["transaction_type"],
                "Notes": row["notes"],
            }
        )
    return output.getvalue().encode("utf-8")
