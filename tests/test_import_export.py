import csv
import io

from expense_analysis.config import AppConfig
from expense_analysis.import_export import export_csv, preview_csv


def test_legacy_csv_import_quotes_commas_and_classifies_refund():
    content = (
        b"Expense,Date,Amount,Category,From,Method\n"
        b'"Lunch, coffee",7/30/26,$12.50,Dining Out,Checking,Card\n'
        b"Returned item,7/29/26,-$5.00,Clothes,Credit,Card\n"
    )
    preview = preview_csv(content, AppConfig())

    assert preview.invalid_count == 0
    assert len(preview.valid_drafts) == 2
    assert preview.valid_drafts[0].description == "Lunch, coffee"
    assert preview.valid_drafts[1].transaction_type == "refund"
    assert preview.valid_drafts[1].amount_cents == 500


def test_unknown_category_becomes_uncategorized():
    content = b"Description,Date,Amount,Category\nSomething,2026-07-30,10.00,Surprise\n"
    preview = preview_csv(content, AppConfig())
    draft = preview.valid_drafts[0]
    assert draft.category == "Uncategorized"
    assert "Imported category: Surprise" in draft.notes


def test_category_rule_applies_when_category_is_missing():
    content = b"Description,Date,Amount,Category\nCoffee shop,2026-07-30,5.00,\n"
    config = AppConfig(category_rules=(("coffee", "Dining Out"),))
    preview = preview_csv(content, config)
    assert preview.valid_drafts[0].category == "Dining Out"


def test_duplicate_is_marked_in_preview():
    content = (
        b"Description,Date,Amount,Category\n"
        b"Coffee,2026-07-30,5.00,Dining Out\n"
        b"Coffee,2026-07-30,5.00,Dining Out\n"
    )
    preview = preview_csv(content, AppConfig())
    assert preview.duplicate_count == 1
    assert len(preview.valid_drafts) == 1


def test_export_uses_real_csv_quoting():
    rows = [
        {
            "id": "abc",
            "transaction_date": "2026-07-30",
            "description": "Lunch, coffee",
            "amount_cents": 1250,
            "category": "Dining Out",
            "account": "Checking",
            "payment_method": "Card",
            "merchant": "Cafe",
            "transaction_type": "expense",
            "notes": "",
        }
    ]
    exported = export_csv(rows)
    parsed = list(csv.DictReader(io.StringIO(exported.decode())))
    assert parsed[0]["Description"] == "Lunch, coffee"
    assert parsed[0]["Amount"] == "12.50"
