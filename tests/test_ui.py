import pandas as pd
import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

from expense_analysis.ui import (
    PLOTLY_CONFIG,
    _kpi_card_markup,
    _style_figure,
    _transaction_list_markup,
)


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


def test_sidebar_has_three_theme_choices_without_navigation_heading():
    app = AppTest.from_file("app.py").run(timeout=30)
    sidebar_html = "".join(block.proto.body for block in app.sidebar.get("html"))

    assert sidebar_html.count("data-jizhang-theme-choice") == 3
    assert all(choice in sidebar_html for choice in ("System", "Light", "Dark"))
    assert "Navigation" not in sidebar_html
    assert "Local only" not in "".join(block.proto.body for block in app.get("html"))


def test_kpi_markup_escapes_content_and_charts_hide_toolbar():
    markup = _kpi_card_markup("<label>", "$12", detail="<detail>", featured=True)

    assert "<label>" not in markup and "<detail>" not in markup
    assert "&lt;label&gt;" in markup and "&lt;detail&gt;" in markup
    assert "featured" in markup
    assert PLOTLY_CONFIG["displayModeBar"] is False

    chart = _style_figure(go.Figure(go.Bar(x=["Food"], y=[12])))
    assert chart.layout.yaxis.griddash == "dot"
    assert chart.data[0].marker.pattern.shape == "."
