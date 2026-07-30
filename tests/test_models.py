from datetime import date

import pytest

from expense_analysis.models import TransactionDraft, parse_amount_cents, parse_date


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("$12.34", 1234),
        ('"$1,234.56"', 123456),
        ("(8.20)", -820),
        ("-5.00", -500),
        (10, 1000),
    ],
)
def test_parse_amount_cents(value, expected):
    assert parse_amount_cents(value) == expected


@pytest.mark.parametrize("value", ["2026-07-30", "7/30/26", "07/30/2026"])
def test_parse_date_formats(value):
    assert parse_date(value) == date(2026, 7, 30)


def test_fingerprint_normalizes_spacing_and_case():
    first = TransactionDraft(
        transaction_date=date(2026, 7, 30),
        description="Coffee Shop",
        amount_cents=525,
        category="Dining Out",
    )
    second = TransactionDraft(
        transaction_date=date(2026, 7, 30),
        description=" coffee   SHOP ",
        amount_cents=525,
        category="dining out",
    )
    assert first.fingerprint == second.fingerprint


def test_transaction_requires_positive_amount():
    with pytest.raises(ValueError, match="greater than zero"):
        TransactionDraft(
            transaction_date=date.today(),
            description="Test",
            amount_cents=0,
            category="Food",
        ).validated()
