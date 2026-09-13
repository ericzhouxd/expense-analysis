"""Presentational helpers: headings, KPI cards, figures, transaction rows."""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .theme import GRID, PALETTE, PLOTLY_CONFIG, PRIMARY_DARK


def _currency(value: float) -> str:
    prefix = "-$" if value < 0 else "$"
    return f"{prefix}{abs(value):,.2f}"


def _percent_delta(value: float | None) -> str | None:
    return None if value is None else f"{value:+.1f}%"


def _style_figure(figure: go.Figure, *, height: int = 380) -> go.Figure:
    horizontal = [
        trace for trace in figure.data if trace.type == "bar" and trace.orientation == "h"
    ]
    category_count = len({str(label) for trace in horizontal for label in trace.y})
    height = max(height, 100 + 36 * category_count) if horizontal else height
    has_legend = len(figure.data) > 1 and figure.layout.showlegend is not False
    figure.update_layout(
        height=height,
        margin={"l": 16, "r": 56 if horizontal else 24, "t": 28, "b": 78 if has_legend else 44},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Departure Mono, monospace", "size": 12},
        hoverlabel={"font": {"family": "Departure Mono, monospace", "size": 12}},
        legend={
            "font": {"size": 11},
            "orientation": "h",
            "yanchor": "top",
            "y": -0.22,
            "x": 0,
        },
        legend_title_text="",
        colorway=PALETTE,
        hovermode=figure.layout.hovermode or "closest",
        uniformtext_minsize=11,
        uniformtext_mode="hide",
        bargap=0.28,
        bargroupgap=0.08,
        showlegend=has_legend,
    )
    figure.update_xaxes(
        showgrid=bool(horizontal),
        gridcolor=GRID,
        griddash="dot",
        automargin=True,
        tickfont={"size": 11},
        title_text=None,
    )
    figure.update_yaxes(
        gridcolor=GRID,
        griddash="dot",
        zeroline=False,
        automargin=True,
        tickfont={"size": 11},
        showgrid=not bool(horizontal),
        title_text=None,
    )
    figure.update_traces(
        marker_pattern_shape=".",
        marker_pattern_solidity=0.10,
        marker_line_width=1,
        marker_line_color=PRIMARY_DARK,
        selector={"type": "bar"},
    )
    bar_index = 0
    for trace in figure.data:
        if trace.type == "bar":
            trace.marker.pattern.shape = (".", "/", "", "\\")[bar_index % 4]
            bar_index += 1
        elif trace.type == "scatter" and "markers" in (trace.mode or ""):
            trace.marker.update(size=7, symbol="square", line={"width": 1, "color": PRIMARY_DARK})
    return figure


def _plotly_chart(figure: go.Figure, *, key: str, height: int = 380) -> None:
    """Render every chart with the same sizing and interaction rules."""
    styled = _style_figure(figure, height=height)
    with st.container(
        height=min(styled.layout.height + 4, 440), border=False, key=f"chart_panel_{key}"
    ):
        st.plotly_chart(styled, width="stretch", height=styled.layout.height, config=PLOTLY_CONFIG)


def _page_heading(kicker: str, title: str, description: str = "") -> None:
    description_html = (
        f'<p class="page-description">{html.escape(description)}</p>' if description else ""
    )
    st.html(
        f"""
        <div class="page-heading">
            <div class="page-kicker">{html.escape(kicker)}</div>
            <h1>{html.escape(title)}</h1>
            {description_html}
        </div>
        """
    )


def _kpi_card_markup(
    label: str,
    value: str,
    *,
    detail: str = "",
    change: float | None = None,
    featured: bool = False,
) -> str:
    if change is None:
        change_html = ""
    else:
        change_class = "calm" if change <= 0 else "attention"
        arrow = "↓" if change < 0 else "↑" if change > 0 else "→"
        change_html = f'<span class="kpi-change {change_class}">{arrow} {abs(change):.1f}%</span>'
    card_class = "kpi-card featured" if featured else "kpi-card"
    return f"""
        <div class="{card_class}">
            <div class="kpi-label">{html.escape(label)}</div>
            <div class="kpi-value">{html.escape(value)}</div>
            <div class="kpi-foot">{change_html}<span>{html.escape(detail)}</span></div>
        </div>
        """


def _kpi_card(
    label: str,
    value: str,
    *,
    detail: str = "",
    change: float | None = None,
    featured: bool = False,
) -> None:
    st.html(
        _kpi_card_markup(
            label,
            value,
            detail=detail,
            change=change,
            featured=featured,
        )
    )


def _section_heading(title: str, description: str = "") -> None:
    description_html = f"<span>{html.escape(description)}</span>" if description else ""
    st.html(f'<div class="section-heading"><h2>{html.escape(title)}</h2>{description_html}</div>')


def _safe_inline(value: object) -> str:
    return html.escape(" ".join(str(value).split()))


def _transaction_list_markup(
    frame: pd.DataFrame,
    *,
    limit: int | None = None,
    focused_transaction_id: str | None = None,
) -> str:
    display = frame.sort_values("transaction_date", ascending=False)
    if focused_transaction_id:
        focused_mask = display["id"].astype(str).eq(focused_transaction_id)
        display = pd.concat([display.loc[focused_mask], display.loc[~focused_mask]])
    if limit:
        display = display.head(limit)
    rows: list[str] = []
    for item in display.to_dict("records"):
        transaction_id = str(item.get("id", ""))
        focused = transaction_id == focused_transaction_id
        row_class: str = "transaction-row is-focused" if focused else "transaction-row"
        focus_attributes: str = (
            f' id="transaction-{html.escape(transaction_id, quote=True)}"'
            ' data-jizhang-transaction-focus="true" tabindex="-1"'
            if focused
            else ""
        )
        transaction_type = str(item["transaction_type"])
        amount = float(item["amount"])
        if transaction_type == "expense":
            amount_text = f"−{_currency(amount)}"
            amount_class = "expense"
        elif transaction_type in {"income", "refund"}:
            amount_text = f"+{_currency(amount)}"
            amount_class = "income"
        else:
            amount_text = _currency(amount)
            amount_class = "transfer"
        merchant = str(item["merchant"]).strip()
        title = merchant or str(item["description"])
        description = (
            str(item["description"]) if merchant and merchant != item["description"] else ""
        )
        details = " · ".join(
            value
            for value in (
                str(item["category"]),
                str(item["account"]).strip(),
                pd.Timestamp(item["transaction_date"]).strftime("%b %d").replace(" 0", " "),
            )
            if value
        )
        secondary = (
            f'<div class="transaction-note">{_safe_inline(description)}</div>'
            if description
            else ""
        )
        rows.append(
            f'<div class="{row_class}"{focus_attributes}>'
            f'<div class="transaction-main">'
            f'<div class="transaction-title">{_safe_inline(title)}</div>'
            f"{secondary}"
            f'<div class="transaction-meta">{_safe_inline(details)}</div>'
            f"</div>"
            f'<div class="transaction-amount {amount_class}">'
            f"{_safe_inline(amount_text)}"
            f"</div>"
            f"</div>"
        )
    return f'<div class="transaction-list">{"".join(rows)}</div>'


def _transaction_list(
    frame: pd.DataFrame,
    *,
    limit: int | None = None,
    focused_transaction_id: str | None = None,
) -> None:
    st.html(
        _transaction_list_markup(
            frame,
            limit=limit,
            focused_transaction_id=focused_transaction_id,
        )
    )
