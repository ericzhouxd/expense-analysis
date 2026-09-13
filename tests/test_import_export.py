import csv
import io

import pytest

from expense_analysis.config import AppConfig
from expense_analysis.import_export import CsvDecodeError, export_csv, preview_csv


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


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252", "utf-16"])
def test_import_reads_the_encodings_spreadsheet_exports_use(encoding):
    text = "Description,Date,Amount,Category\nCafé purchase,2026-07-30,4.25,Dining Out\n"
    preview = preview_csv(text.encode(encoding), AppConfig())

    assert preview.invalid_count == 0
    assert len(preview.valid_drafts) == 1
    assert preview.valid_drafts[0].description == "Café purchase"


def test_import_falls_back_when_cp1252_cannot_map_a_byte():
    # 0x81 is undefined in cp1252, so this only decodes via the latin-1 fallback.
    text = "Description,Date,Amount,Category\nOdd\x81 name,2026-07-30,4.25,Dining Out\n"
    preview = preview_csv(text.encode("latin-1"), AppConfig())

    assert len(preview.valid_drafts) == 1


def test_binary_file_reports_a_readable_error():
    # Decodes as utf-8, but the NUL means it is not a text CSV.
    content = b"PK\x03\x04\x00\x00binary spreadsheet data"
    with pytest.raises(CsvDecodeError, match="Re-export it as CSV"):
        preview_csv(content, AppConfig())


def test_non_utf8_file_no_longer_raises_a_decode_error():
    content = "Description,Date,Amount\nCafé,2026-07-30,4.25\n".encode("cp1252")
    preview = preview_csv(content, AppConfig())
    assert len(preview.valid_drafts) == 1


def test_import_reports_out_of_range_and_impossible_dates():
    content = (
        b"Description,Date,Amount\n"
        b"Future thing,2099-01-01,10.00\n"
        b"Impossible thing,2026-02-30,10.00\n"
    )
    preview = preview_csv(content, AppConfig())

    assert preview.invalid_count == 2
    assert not preview.valid_drafts
    errors = [row.errors for row in preview.rows]
    assert "Date must be between" in errors[0][0]
    assert "is not a recognised date" in errors[1][0]
