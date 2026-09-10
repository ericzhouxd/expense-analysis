from datetime import date

import pandas as pd
import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

from expense_analysis.config import AppConfig
from expense_analysis.database import Database
from expense_analysis.models import TransactionDraft
from expense_analysis.ui import (
    PLOTLY_CONFIG,
    _category_options,
    _get_transaction,
    _kpi_card_markup,
    _style_figure,
    _transaction_list_markup,
)


def render_add_transaction_dialog(database):
    from expense_analysis.config import AppConfig
    from expense_analysis.ui import _add_transaction_dialog

    _add_transaction_dialog(database, AppConfig())


class CachedDatabaseProxy:
    """Represents a Database instance retained across a Streamlit source reload."""

    def __init__(self, database):
        self.database = database

    def list_transactions(self):
        return self.database.list_transactions()

    def get_spending_plan(self):
        return self.database.get_spending_plan()


def test_transaction_list_is_compact_html_and_escapes_user_content():
    frame = pd.DataFrame(
        [
            {
                "id": "safe-id",
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

    markup = _transaction_list_markup(frame, focused_transaction_id="safe-id")

    assert "\n" not in markup
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "Lunch with coffee" in markup
    assert 'data-jizhang-transaction-focus="true"' in markup
    assert 'id="transaction-safe-id"' in markup
    assert markup.startswith('<div class="transaction-list">')


def test_sidebar_has_three_theme_choices_without_navigation_heading(tmp_path, monkeypatch):
    from expense_analysis import ui

    database = Database(tmp_path / "sidebar.sqlite3")
    database.initialize()
    monkeypatch.setattr(ui, "_database", lambda: database)
    monkeypatch.setattr(ui, "load_config", AppConfig)
    app = AppTest.from_file("app.py").run(timeout=30)
    sidebar_html = "".join(block.proto.body for block in app.sidebar.get("html"))

    assert sidebar_html.count("data-jizhang-theme-choice") == 3
    assert all(choice in sidebar_html for choice in ("System", "Light", "Dark"))
    assert "Navigation" not in sidebar_html
    assert "Local only" not in "".join(block.proto.body for block in app.get("html"))
    assert "Add transaction" not in app.sidebar.radio[0].options


def test_kpi_markup_escapes_content_and_charts_hide_toolbar():
    markup = _kpi_card_markup("<label>", "$12", detail="<detail>", featured=True)

    assert "<label>" not in markup and "<detail>" not in markup
    assert "&lt;label&gt;" in markup and "&lt;detail&gt;" in markup
    assert "featured" in markup
    assert PLOTLY_CONFIG["displayModeBar"] is False

    chart = _style_figure(go.Figure(go.Bar(x=["Food"], y=[12])))
    assert chart.layout.yaxis.griddash == "dot"
    assert chart.data[0].marker.pattern.shape == "."


def test_category_charts_keep_every_label_and_comparisons_use_distinct_patterns():
    labels = [f"Category {index}" for index in range(20)]
    chart = _style_figure(go.Figure(go.Bar(x=list(range(20)), y=labels, orientation="h")))
    assert chart.layout.height >= 20 * 36 + 100
    assert list(chart.data[0].y) == labels
    chart = _style_figure(
        go.Figure(
            [
                go.Bar(x=[1], y=[20], name="2025"),
                go.Bar(x=[1], y=[30], name="2026"),
            ]
        )
    )
    assert chart.data[0].marker.pattern.shape != chart.data[1].marker.pattern.shape
    assert chart.layout.legend.orientation == "h"


def test_add_transaction_dialog_saves_transaction(tmp_path):
    database = Database(tmp_path / "dialog.sqlite3")
    database.initialize()
    app = AppTest.from_function(render_add_transaction_dialog, args=(database,)).run()
    category = next(field for field in app.selectbox if field.label == "Category")

    next(field for field in app.text_input if field.label == "Description").set_value(
        "Synthetic dinner"
    )
    next(field for field in app.number_input if field.label == "Amount").set_value(12.5)
    next(field for field in app.text_area if field.label == "Notes").set_value("Saved in dialog")
    next(button for button in app.button if button.label == "Save transaction").click().run()

    assert database.count_transactions() == 1
    transaction = database.list_transactions()[0]
    assert transaction["description"] == "Synthetic dinner"
    assert app.session_state["saved_transaction_id"] == transaction["id"]
    assert app.session_state["show_saved_transaction_notice"] is True
    assert category.proto.accept_new_options is True


def test_hot_reloaded_database_supports_category_and_transaction_lookups(tmp_path):
    database = Database(tmp_path / "cached.sqlite3")
    database.initialize()
    transaction_id = database.add_transaction(
        TransactionDraft(
            transaction_date=date(2026, 7, 30),
            description="Synthetic repair",
            amount_cents=1250,
            category="New category",
        )
    )
    cached_database = CachedDatabaseProxy(database)

    assert "New category" in _category_options(cached_database, AppConfig())
    assert _get_transaction(cached_database, transaction_id)["description"] == "Synthetic repair"


def test_transactions_page_opens_dialog_and_reveals_saved_transaction(tmp_path, monkeypatch):
    from expense_analysis import ui

    database = Database(tmp_path / "ui.sqlite3")
    database.initialize()
    transaction_id = database.add_transaction(
        TransactionDraft(
            transaction_date=date(2026, 7, 30),
            description="Synthetic dinner",
            amount_cents=1250,
            category="Food",
            account="Checking",
            payment_method="Card",
            notes="Saved in dialog",
        )
    )
    monkeypatch.setattr(ui, "_database", lambda: database)
    monkeypatch.setattr(ui, "load_config", AppConfig)

    app = AppTest.from_file("app.py").run()
    app.sidebar.radio[0].set_value("Transactions").run()
    next(button for button in app.button if button.label == "Add transaction").click().run()
    assert any(field.label == "Notes" for field in app.text_area)
    assert any(button.label == "Save transaction" for button in app.button)

    app.session_state["saved_transaction_id"] = transaction_id
    app.session_state["show_saved_transaction_notice"] = True
    app.run()
    next(button for button in app.button if button.label == "View").click().run()
    page_html = "".join(block.proto.body for block in app.get("html"))
    assert 'data-jizhang-transaction-focus="true"' in page_html
    assert "Synthetic dinner" in page_html
