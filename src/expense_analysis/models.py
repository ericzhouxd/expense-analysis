from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from .config import TRANSACTION_TYPES

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y", "%m-%d-%y", "%m-%d-%Y")
# Any real ledger entry is later than this; earlier values are typos, not history.
MIN_TRANSACTION_DATE = date(1900, 1, 1)
# Allow post-dated/planned entries up to a year ahead while rejecting obvious typos.
MAX_FUTURE_TRANSACTION_DAYS = 366


def parse_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if value is None:
        raise ValueError("Date is required")

    cleaned = str(value).strip().strip("\"'").strip()
    if not cleaned:
        raise ValueError("Date is required")
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Date {cleaned!r} is not a recognised date (try YYYY-MM-DD)")


def validate_transaction_date(value: date | datetime | str, *, today: date | None = None) -> date:
    """Parse a date and enforce the transaction range policy.

    `today` is injectable so callers and tests can pin the future cutoff.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("Date is required")
    parsed = parse_date(value)
    latest = (today or date.today()) + timedelta(days=MAX_FUTURE_TRANSACTION_DAYS)
    if parsed < MIN_TRANSACTION_DATE or parsed > latest:
        raise ValueError(
            f"Date must be between {MIN_TRANSACTION_DATE.isoformat()} and {latest.isoformat()}"
        )
    return parsed


def parse_amount_cents(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Amount must be a number")
    if isinstance(value, int):
        return value * 100

    if value is None:
        raise ValueError("Amount is required")

    cleaned = str(value).strip().strip("\"'").strip()
    if not cleaned:
        raise ValueError("Amount is required")

    negative_parentheses = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.removeprefix("(").removesuffix(")")
    cleaned = re.sub(r"[$,\s]", "", cleaned)
    if not cleaned:
        raise ValueError("Amount is required")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Amount {cleaned!r} is not a number") from exc
    if not amount.is_finite():
        raise ValueError(f"Amount {cleaned!r} is not a number")
    if negative_parentheses:
        amount = -amount
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class TransactionDraft:
    transaction_date: date
    description: str
    amount_cents: int
    category: str
    account: str = ""
    payment_method: str = ""
    merchant: str = ""
    transaction_type: str = "expense"
    notes: str = ""

    def validated(self) -> TransactionDraft:
        description = self.description.strip()
        category = self.category.strip() or "Uncategorized"
        transaction_type = self.transaction_type.strip().casefold()
        if not description:
            raise ValueError("Description is required")
        if self.amount_cents <= 0:
            raise ValueError("Amount must be greater than zero")
        if transaction_type not in TRANSACTION_TYPES:
            raise ValueError(f"Transaction type must be one of: {', '.join(TRANSACTION_TYPES)}")
        return TransactionDraft(
            transaction_date=validate_transaction_date(self.transaction_date),
            description=description,
            amount_cents=self.amount_cents,
            category=category,
            account=self.account.strip(),
            payment_method=self.payment_method.strip(),
            merchant=self.merchant.strip(),
            transaction_type=transaction_type,
            notes=self.notes.strip(),
        )

    @property
    def fingerprint(self) -> str:
        parts = (
            self.transaction_date.isoformat(),
            normalize_text(self.description),
            str(self.amount_cents),
            normalize_text(self.category),
            normalize_text(self.account),
            normalize_text(self.payment_method),
            normalize_text(self.merchant),
            self.transaction_type,
        )
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def new_transaction_id() -> str:
    return uuid.uuid4().hex
