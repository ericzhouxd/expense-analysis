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


def test_import_uses_learned_merchant_history_for_unknown_labels():
    content = (
        b"Description,Date,Amount,Category,Merchant\n"
        b"Synthetic latte,2026-07-30,4.25,Surprise,Corner Cafe\n"
    )
    preview = preview_csv(content, AppConfig(), merchant_suggestions={"corner cafe": "Dining Out"})
    draft = preview.valid_drafts[0]
    assert draft.category == "Dining Out"
    assert "Imported category: Surprise" not in draft.notes


def test_import_keeps_known_category_over_merchant_history():
    content = (
        b"Description,Date,Amount,Category,Merchant\n"
        b"Synthetic latte,2026-07-30,4.25,Food,Corner Cafe\n"
    )
    preview = preview_csv(content, AppConfig(), merchant_suggestions={"corner cafe": "Dining Out"})
    assert preview.valid_drafts[0].category == "Food"


def test_import_ignores_merchant_suggestions_outside_the_vocabulary():
    content = (
        b"Description,Date,Amount,Category,Merchant\n"
        b"Synthetic latte,2026-07-30,4.25,Surprise,Corner Cafe\n"
    )
    preview = preview_csv(content, AppConfig(), merchant_suggestions={"corner cafe": "Nonexistent"})
    draft = preview.valid_drafts[0]
    assert draft.category == "Uncategorized"
    assert "Imported category: Surprise" in draft.notes


def test_exported_backup_reimports_as_duplicates_with_every_field():
    rows = [
        {
            "id": "synthetic",
            "transaction_date": "2026-07-30",
            "description": "Synthetic coffee",
            "amount_cents": 450,
            "category": "Dining Out",
            "account": "Checking",
            "payment_method": "Apple Pay",
            "merchant": "Cafe",
            "transaction_type": "expense",
            "notes": "記帳 note",
        }
    ]
    exported = export_csv(rows)
    assert exported.startswith(b"\xef\xbb\xbf")  # Excel detects UTF-8 from the BOM.
    first = preview_csv(exported, AppConfig())
    draft = first.valid_drafts[0]
    assert (draft.payment_method, draft.notes) == ("Apple Pay", "記帳 note")
    again = preview_csv(exported, AppConfig(), {draft.fingerprint})
    assert again.duplicate_count == 1 and not again.valid_drafts


def test_row_with_unquoted_comma_is_invalid_instead_of_crashing():
    preview = preview_csv(
        b"Date,Description,Amount\n2026-03-01,Lunch, tacos,12.50\n2026-03-02,Bus,2.75\n",
        AppConfig(),
    )
    assert preview.invalid_count == 1
    assert "more values than the header" in "; ".join(preview.rows[0].errors)
    assert [d.description for d in preview.valid_drafts] == ["Bus"]


@pytest.mark.parametrize(
    ("convention", "negative", "positive"),
    [
        ("positive_expense", "refund", "expense"),
        ("negative_expense_refund", "expense", "refund"),
        ("negative_expense_income", "expense", "income"),
    ],
)
def test_sign_convention_sets_untyped_rows_only(convention, negative, positive):
    content = (
        b"Date,Description,Amount,Type\n"
        b"2026-03-01,Card purchase,-20.00,\n"
        b"2026-03-02,Credit,15.00,\n"
        b"2026-03-03,Explicit,-5.00,transfer\n"
    )
    drafts = preview_csv(content, AppConfig(), sign_convention=convention).valid_drafts
    assert [d.transaction_type for d in drafts] == [negative, positive, "transfer"]
    assert all(d.amount_cents > 0 for d in drafts)
