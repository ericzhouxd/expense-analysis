from datetime import date, timedelta

import pytest

from expense_analysis.models import (
    MAX_FUTURE_TRANSACTION_DAYS,
    TransactionDraft,
    parse_amount_cents,
    parse_date,
    validate_transaction_date,
)


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


@pytest.mark.parametrize("value", [None, "", "   ", '"  "'])
def test_missing_date_says_it_is_required(value):
    with pytest.raises(ValueError, match="^Date is required$"):
        parse_date(value)


@pytest.mark.parametrize("value", [None, "", "   ", "$$", "()"])
def test_missing_amount_says_it_is_required(value):
    with pytest.raises(ValueError, match="^Amount is required$"):
        parse_amount_cents(value)


@pytest.mark.parametrize("value", ["13/45/2026", "not a date", "2026-13-01"])
def test_unparseable_date_message_is_written_for_users(value):
    with pytest.raises(ValueError) as error:
        parse_date(value)
    message = str(error.value)
    assert value in message
    assert "None" not in message
    assert "recognised date" in message


@pytest.mark.parametrize(
    "value",
    ["abc", float("nan"), float("inf"), float("-inf"), "nan", "Infinity"],
)
def test_unparseable_amount_message_is_written_for_users(value):
    with pytest.raises(ValueError) as error:
        parse_amount_cents(value)
    message = str(error.value)
    assert "is not a number" in message
    assert "None" not in message


@pytest.mark.parametrize("value", ["02302026", "2026-02-30", "13452026", "99999999"])
def test_parse_date_reports_a_human_readable_error(value):
    with pytest.raises(ValueError, match="is not a recognised date"):
        parse_date(value)


@pytest.mark.parametrize("value", ["", "   ", None, "2026-02-30", "not a date"])
def test_validate_transaction_date_rejects_empty_and_unparseable(value):
    with pytest.raises(ValueError):
        validate_transaction_date(value, today=date(2026, 9, 12))


def test_validate_transaction_date_enforces_the_documented_range():
    today = date(2026, 9, 12)
    latest = today + timedelta(days=MAX_FUTURE_TRANSACTION_DAYS)

    assert validate_transaction_date("2026-09-12", today=today) == today
    assert validate_transaction_date(latest, today=today) == latest

    with pytest.raises(ValueError, match="Date must be between"):
        validate_transaction_date("1899-12-31", today=today)
    with pytest.raises(ValueError, match="Date must be between"):
        validate_transaction_date(latest + timedelta(days=1), today=today)


def test_transaction_draft_rejects_an_out_of_range_date():
    with pytest.raises(ValueError, match="Date must be between"):
        TransactionDraft(
            transaction_date=date(2099, 1, 1),
            description="Test",
            amount_cents=100,
            category="Food",
        ).validated()
