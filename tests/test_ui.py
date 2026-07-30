import pandas as pd

from expense_analysis.ui import _transaction_list_markup


def test_transaction_list_is_compact_html_and_escapes_user_content():
    frame = pd.DataFrame(
        [
            {
                "transaction_date": "2026-07-30",
                "transaction_type": "expense",
                "amount": 12.5,
                "merchant": "<script>alert('x')</script>",
                "description": "Lunch\nwith coffee",
                "category": "Dining Out",
                "account": "Checking",
            }
        ]
    )

    markup = _transaction_list_markup(frame)

    assert "\n" not in markup
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "Lunch with coffee" in markup
    assert markup.startswith('<div class="transaction-list">')
