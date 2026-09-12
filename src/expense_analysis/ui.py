from __future__ import annotations

import html
import sqlite3
from dataclasses import asdict
from datetime import date
from typing import cast

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .analytics import (
    academic_period_spending,
    cash_flow_by_month,
    category_spending,
    comparable_year_months,
    monthly_spending,
    period_metrics,
    recurring_transactions,
    savings_summary,
    spending_anomalies,
    spending_drivers,
    transactions_frame,
)
from .budget_ui import render_budget_page
from .choices import choice_options
from .config import DATABASE_PATH, AppConfig, load_config
from .database import Database, DuplicateTransactionError
from .import_export import ImportPreview, export_csv, preview_csv
from .models import TransactionDraft, parse_amount_cents
from .presentation import inject_theme
from .spending_plan import calculate_plan
from .transaction_edits import TransactionChange, apply_changes, collect_changes

PRIMARY = "#859A19"
PRIMARY_DARK = "#657900"
SAGE = "#A6AC92"
MINT = "rgba(133,154,25,0.16)"
GOLD = "#B79738"
CORAL = "#CA6353"
GRID = "rgba(128,132,120,0.25)"
PALETTE = (
    PRIMARY,
    GOLD,
    "#718E7E",
    "#9F7A66",
    "#758DA3",
    "#9B8AAD",
    "#7F9972",
    CORAL,
    "#A39A78",
    "#8A928C",
)
PLOTLY_CONFIG = {
    "displayModeBar": False,
    "responsive": True,
    "scrollZoom": False,
}
# The sidebar activity filters are recreated whenever their generation changes, so a
# filter that predates a new transaction cannot keep it out of the dashboard.
_ACTIVITY_FILTER_GENERATION = "activity_filter_generation"
_ACTIVITY_FILTER_SIGNATURE = "activity_filter_signature"


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


@st.cache_resource
def _database() -> Database:
    """Open the local database and initialize schema v2 (student spending plans)."""
    database = Database()
    database.initialize()
    return database


def _render_empty_state() -> None:
    st.html(
        """
        <div class="empty-card">
            <h2>No transactions yet</h2>
            <p>
                Add a transaction or import a CSV. Everything is stored
                in a local SQLite database and stays on this computer.
            </p>
        </div>
        """
    )


def _invalidate_activity_filters() -> None:
    """Rebuild the sidebar activity filters with their defaults on the next run.

    The dashboard and insights honour the activity filters, so a filter left over
    from before a transaction is added or imported can keep the new data out of the
    analysis. Bumping the generation recreates the widgets instead of restoring the
    stale selection.
    """
    st.session_state[_ACTIVITY_FILTER_GENERATION] = (
        st.session_state.get(_ACTIVITY_FILTER_GENERATION, 0) + 1
    )


def _clear_focused_transaction() -> None:
    """Drop a saved-transaction highlight once the activity filters change.

    The "View" confirmation intentionally reveals a new transaction even when the
    active filters exclude it. The highlight is a one-off reveal, so the first
    filter edit should return the list to the filtered selection.
    """
    st.session_state.pop("focused_transaction_id", None)


def _filtered_data(
    database: Database, config: AppConfig
) -> tuple[list[dict[str, object]], list[dict[str, object]], pd.DataFrame]:
    all_rows = database.list_transactions()
    all_frame = transactions_frame(all_rows, config)
    if all_frame.empty:
        return all_rows, all_rows, all_frame

    minimum = all_frame["transaction_date"].min().date()
    maximum = all_frame["transaction_date"].max().date()
    category_options = choice_options(database, config, "category")
    account_options = choice_options(database, config, "account")
    # Recreate the filters when the ledger range or its choice lists change, matching the
    # previous behaviour of dropping options that no longer exist.
    signature = (minimum, maximum, tuple(category_options), tuple(account_options))
    if st.session_state.get(_ACTIVITY_FILTER_SIGNATURE) != signature:
        st.session_state[_ACTIVITY_FILTER_SIGNATURE] = signature
        _invalidate_activity_filters()
    filter_generation = st.session_state.get(_ACTIVITY_FILTER_GENERATION, 0)
    with st.sidebar.expander("Filter activity", expanded=False):
        selected_range = st.date_input(
            "Date range",
            value=(minimum, maximum),
            min_value=minimum,
            max_value=max(maximum, date.today()),
            key=f"activity_date_range_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        if isinstance(selected_range, tuple) and len(selected_range) == 2:
            start, end = selected_range
        else:
            start, end = minimum, maximum
        search = st.text_input(
            "Search",
            placeholder="Description, merchant, notes…",
            key=f"activity_search_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        selected_categories = st.multiselect(
            "Categories",
            category_options,
            placeholder="All categories",
            accept_new_options=True,
            key=f"activity_categories_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        selected_types = st.multiselect(
            "Transaction types",
            ["expense", "refund", "income", "transfer"],
            placeholder="All types",
            key=f"activity_types_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        selected_accounts = st.multiselect(
            "Accounts",
            account_options,
            placeholder="All accounts",
            accept_new_options=True,
            key=f"activity_accounts_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
    if (
        start == minimum
        and end == maximum
        and not search.strip()
        and not selected_categories
        and not selected_types
        and not selected_accounts
    ):
        return all_rows, all_rows, all_frame
    rows = database.list_transactions(
        start=start,
        end=end,
        categories=selected_categories,
        transaction_types=selected_types,
        accounts=selected_accounts,
        search=search,
    )
    return all_rows, rows, transactions_frame(rows, config)


def _render_dashboard(
    database: Database,
    frame: pd.DataFrame,
    all_rows: list[dict[str, object]],
) -> None:
    _page_heading(
        "OVERVIEW",
        "Overview",
    )
    if frame.empty:
        _render_empty_state()
        return

    metrics = period_metrics(frame, personal_only=True)
    latest_month = str(frame["month"].max())
    plan = database.get_spending_plan()
    budget_month = None
    if plan:
        budget_month = next(
            (
                month
                for month in calculate_plan(plan, all_rows)["months"]
                if month["month"] == latest_month
            ),
            None,
        )
    budget_remaining = budget_month["remaining"] / 100 if budget_month else None
    period_detail = "Partial month" if metrics.is_partial else "Complete month"
    st.html(
        '<div class="kpi-grid">'
        + _kpi_card_markup(
            "Personal spending",
            _currency(metrics.spending),
            detail=metrics.period_label,
            change=metrics.change_from_previous,
            featured=True,
        )
        + _kpi_card_markup(
            "Budget remaining",
            _currency(budget_remaining) if budget_remaining is not None else "Not set",
            detail=f"{latest_month} · full ledger, with rollover"
            if budget_remaining is not None
            else "Open Budgets to set or view your plan",
        )
        + _kpi_card_markup(
            "Compared with last month",
            _percent_delta(metrics.change_from_previous) or "No baseline",
            detail="Through the same day" if metrics.is_partial else "Full month",
        )
        + _kpi_card_markup(
            "Month-end outlook",
            (
                _currency(metrics.projected_month_end)
                if metrics.is_partial
                else _currency(metrics.spending)
            ),
            detail=period_detail,
        )
        + "</div>"
    )

    monthly = monthly_spending(frame, personal_only=True)
    personal_frame = frame[frame["spending_class"].eq("Personal")]
    drivers = spending_drivers(personal_frame)
    recurring = recurring_transactions(personal_frame)
    anomalies = spending_anomalies(personal_frame)

    if metrics.change_from_previous is None:
        trend_title = "Your monthly spending rhythm"
    elif metrics.change_from_previous > 0:
        trend_title = f"Spending rose {abs(metrics.change_from_previous):.0f}% from last month"
    else:
        trend_title = f"Spending eased {abs(metrics.change_from_previous):.0f}% from last month"

    left, right = st.columns((1.7, 1), gap="large")
    with left:
        _section_heading(
            trend_title,
            f"Three-month average: {_currency(metrics.monthly_average)}",
        )
        if monthly.empty:
            st.info("Add expense history to see trends.")
        else:
            trend = go.Figure()
            x_values = monthly["month"].dt.to_timestamp()
            trend.add_trace(
                go.Scatter(
                    x=x_values,
                    y=monthly["spending"],
                    name="Monthly spending",
                    mode="lines+markers",
                    line={"color": PRIMARY, "width": 2.5, "shape": "linear"},
                    marker={"size": 7, "color": PRIMARY, "line": {"width": 2, "color": "white"}},
                    fill="tozeroy",
                    fillcolor=MINT,
                    hovertemplate="%{x|%b %Y}<br>$%{y:,.2f}<extra></extra>",
                )
            )
            trend.add_trace(
                go.Scatter(
                    x=x_values,
                    y=monthly["rolling_3"],
                    name="3-month average",
                    mode="lines",
                    line={"color": GOLD, "width": 1.8, "dash": "dot"},
                    hovertemplate="%{x|%b %Y}<br>$%{y:,.2f}<extra></extra>",
                )
            )
            trend.update_yaxes(tickprefix="$", rangemode="tozero")
            trend.update_layout(hovermode="x unified")
            _plotly_chart(trend, key="spending_trend", height=360)

    with right:
        _section_heading("What changed")
        insight_rows: list[str] = []
        for driver in drivers.head(3).to_dict("records"):
            change = float(driver["change"])
            if change == 0:
                continue
            direction = "added" if change > 0 else "fell by"
            tone = "attention" if change > 0 else "calm"
            insight_rows.append(
                f"""
                <div class="insight-row">
                    <span class="insight-dot {tone}"></span>
                    <div><strong>{html.escape(str(driver["category"]))}</strong>
                    {direction} {_currency(abs(change))}</div>
                </div>
                """
            )
        if not anomalies.empty:
            insight_rows.append(
                f"""
                <div class="insight-row">
                    <span class="insight-dot attention"></span>
                    <div><strong>{len(anomalies)} unusual purchase(s)</strong>
                    may be worth reviewing</div>
                </div>
                """
            )
        if not recurring.empty:
            insight_rows.append(
                f"""
                <div class="insight-row">
                    <span class="insight-dot neutral"></span>
                    <div><strong>{len(recurring)} recurring pattern(s)</strong>
                    detected in your history</div>
                </div>
                """
            )
        if not insight_rows:
            insight_rows.append(
                """
                <div class="insight-row">
                    <span class="insight-dot calm"></span>
                    <div><strong>Nothing unusual</strong>
                    Your recent spending looks steady</div>
                </div>
                """
            )
        st.html(f'<div class="insight-card">{"".join(insight_rows)}</div>')

    categories = category_spending(frame, personal_only=True)
    left, right = st.columns((1.15, 1), gap="large")
    with left:
        category_title = (
            f"{categories.iloc[0]['category']} is your largest category"
            if not categories.empty
            else "Where your money went"
        )
        _section_heading(category_title, "Personal spending in the selected range")
        if categories.empty:
            st.info("No personal expenses in the selected range.")
        else:
            category_chart = px.bar(
                categories.sort_values("spending"),
                x="spending",
                y="category",
                orientation="h",
                text_auto="$.3s",
                labels={"spending": "Spending", "category": ""},
            )
            category_chart.update_traces(
                marker_color=[SAGE] * (len(categories) - 1) + [PRIMARY],
                marker_line_width=0,
                hovertemplate="<b>%{y}</b><br>$%{x:,.2f}<extra></extra>",
                textposition="outside",
                cliponaxis=False,
            )
            category_chart.update_layout(showlegend=False)
            category_chart.update_xaxes(tickprefix="$", rangemode="tozero")
            category_chart.update_yaxes(gridcolor="rgba(0,0,0,0)")
            _plotly_chart(category_chart, key="category_breakdown", height=340)

    with right:
        _section_heading(
            f"Budget progress · {latest_month}",
        )
        if budget_month is None:
            st.html(
                """
                <div class="soft-empty">
                    <strong>No spending plan for this month</strong>
                </div>
                """
            )
        else:
            st.metric("Everyday allowance", _currency(budget_month["allowance"] / 100))
            st.metric("Everyday spent", _currency(budget_month["flexible_spent"] / 100))
            st.caption(
                f"Carry within this quarter: {_currency(budget_month['rollover'] / 100)}. "
                "Bill reserves, tuition and the full breakdown are on Budgets."
            )

    _section_heading("Recent activity", "Your latest local transactions")
    _transaction_list(frame, limit=6)

    with st.expander("Explore comparisons and spending mix"):
        class_totals = (
            frame[frame["transaction_type"].isin(["expense", "refund"])]
            .groupby("spending_class", as_index=False)["spending"]
            .sum()
        )
        year_months = comparable_year_months(frame)
        left, right = st.columns(2)
        with left:
            st.markdown("#### Like-for-like monthly view")
            if not year_months.empty:
                comparison = px.bar(
                    year_months,
                    x="month_number",
                    y="spending",
                    color=year_months["year"].astype(str),
                    barmode="group",
                    labels={
                        "month_number": "Month",
                        "spending": "Spending",
                        "color": "Year",
                    },
                    color_discrete_sequence=(PRIMARY, SAGE, GOLD, CORAL),
                )
                comparison.update_xaxes(
                    tickmode="array",
                    tickvals=list(range(1, 13)),
                    ticktext=[
                        "Jan",
                        "Feb",
                        "Mar",
                        "Apr",
                        "May",
                        "Jun",
                        "Jul",
                        "Aug",
                        "Sep",
                        "Oct",
                        "Nov",
                        "Dec",
                    ],
                )
                comparison.update_yaxes(tickprefix="$")
                _plotly_chart(comparison, key="period_comparison", height=300)
        with right:
            st.markdown("#### Fixed and personal spending")
            if not class_totals.empty:
                mix = px.bar(
                    class_totals,
                    x="spending",
                    y=["Total"] * len(class_totals),
                    color="spending_class",
                    orientation="h",
                    text_auto="$.3s",
                    color_discrete_map={
                        "Personal": PRIMARY,
                        "Fixed": GOLD,
                        "Uncategorized": "#A3AAA5",
                    },
                    labels={"spending": "Spending", "spending_class": ""},
                )
                mix.update_yaxes(visible=False)
                mix.update_xaxes(visible=False)
                _plotly_chart(mix, key="spending_mix", height=220)


def _category_options(database: Database, config: AppConfig) -> list[str]:
    return choice_options(database, config, "category")


def _get_transaction(database: Database, transaction_id: str) -> dict[str, object] | None:
    transaction_reader = getattr(database, "get_transaction", None)
    if transaction_reader is not None:
        return cast("dict[str, object] | None", transaction_reader(transaction_id))
    return next(
        (row for row in database.list_transactions() if str(row.get("id", "")) == transaction_id),
        None,
    )


def _reset_transaction_editor() -> None:
    st.session_state.pop("transaction_editor_baseline", None)
    st.session_state["transaction_editor_generation"] = (
        st.session_state.get("transaction_editor_generation", 0) + 1
    )


@st.dialog("Review transaction changes", width="large")
def _review_transaction_changes(database: Database, changes: list[TransactionChange]) -> None:
    deletions = sum(change.after is None for change in changes)
    st.write(f"{len(changes) - deletions} transaction(s) edited · {deletions} marked for deletion")
    preview = []
    for change in changes:
        if change.after is None:
            preview.append(
                {
                    "Transaction": change.before.description,
                    "Field": "Delete transaction",
                    "Before": f"{change.before.transaction_date} · "
                    f"{_currency(change.before.amount_cents / 100)}",
                    "After": "Permanently deleted",
                }
            )
            continue
        for field, before in asdict(change.before).items():
            after = getattr(change.after, field)
            if before != after:
                preview.append(
                    {
                        "Transaction": change.before.description,
                        "Field": field.replace("_", " ").replace("amount cents", "amount").title(),
                        "Before": _currency(before / 100)
                        if field == "amount_cents"
                        else str(before),
                        "After": _currency(after / 100) if field == "amount_cents" else str(after),
                    }
                )
    st.dataframe(pd.DataFrame(preview), hide_index=True, width="stretch")
    st.caption("Close this review to keep editing. Nothing is saved until you confirm.")
    confirmed = not deletions or st.checkbox("I understand that these deletions are permanent.")
    if st.button("Confirm changes", type="primary", disabled=not confirmed):
        try:
            apply_changes(database, changes)
        except ValueError as exc:
            st.error(str(exc))
        except sqlite3.Error:
            st.error("Nothing was saved. The database could not complete the changes. Try again.")
        else:
            _reset_transaction_editor()
            st.session_state["transaction_editor_saved"] = len(changes)
            st.rerun()


def _render_transactions(database: Database, frame: pd.DataFrame, config: AppConfig) -> None:
    heading, add_action = st.columns((5, 1), vertical_alignment="bottom", gap="large")
    with heading:
        _page_heading(
            "ACTIVITY",
            "Transactions",
            "Browse comfortably or switch to the editing table when you need it.",
        )
    with add_action:
        if st.button(
            "Add transaction",
            type="primary",
            key="open_add_transaction",
            width="stretch",
        ):
            _add_transaction_dialog(database, config)

    saved_transaction_id = st.session_state.get("saved_transaction_id")
    if saved_transaction_id and st.session_state.get("show_saved_transaction_notice"):
        _, notice_column = st.columns((4, 2))
        with notice_column:
            notice = st.empty()
            with notice.container(
                border=True,
                key="saved_transaction_notice",
                horizontal=True,
                horizontal_alignment="right",
                vertical_alignment="center",
                gap="small",
            ):
                st.markdown("**Transaction saved.**")
                view_saved = st.button(
                    "View",
                    key="view_saved_transaction",
                    type="tertiary",
                )
            if view_saved:
                st.session_state["focused_transaction_id"] = saved_transaction_id
                st.session_state["show_saved_transaction_notice"] = False
                st.session_state["transaction_view"] = "List"
                notice.empty()

    focused_transaction_id = st.session_state.get("focused_transaction_id")
    if focused_transaction_id:
        focused_row = _get_transaction(database, focused_transaction_id)
        if focused_row:
            focused_frame = transactions_frame([focused_row], config)
            frame = (
                pd.concat([focused_frame, frame], ignore_index=True)
                .drop_duplicates(subset="id", keep="first")
                .reset_index(drop=True)
            )
    if frame.empty:
        st.info("No transactions match the current filters.")
        return

    view = st.segmented_control(
        "Transaction view",
        ["List", "Edit table"],
        default="List",
        label_visibility="collapsed",
        key="transaction_view",
    )
    if view == "List":
        _transaction_list(frame, focused_transaction_id=focused_transaction_id)
        return

    if saved_count := st.session_state.pop("transaction_editor_saved", None):
        st.success(f"Saved changes to {saved_count} transaction(s).")
    st.caption("Edit cells, then review the changes. Deletions require explicit confirmation.")
    editor_frame = pd.DataFrame(
        {
            "Delete": False,
            "ID": frame["id"],
            "Date": frame["transaction_date"].dt.date,
            "Description": frame["description"],
            "Amount": frame["amount"],
            "Category": frame["category"],
            "Account": frame["account"],
            "Payment method": frame["payment_method"],
            "Merchant": frame["merchant"],
            "Type": frame["transaction_type"],
            "Notes": frame["notes"],
        }
    )
    baseline = st.session_state.get("transaction_editor_baseline")
    if baseline is None or tuple(baseline["ID"]) != tuple(editor_frame["ID"]):
        _reset_transaction_editor()
        st.session_state["transaction_editor_baseline"] = editor_frame.copy(deep=True)
    editor_frame = st.session_state["transaction_editor_baseline"]
    choice_columns = {
        "Category": "category",
        "Account": "account",
        "Payment method": "payment_method",
    }
    display_frame = editor_frame.copy(deep=True)
    for column in choice_columns:
        display_frame[column] = display_frame[column].map(lambda value: [value] if value else [])
    st.caption("Category, account and payment method: remove the current choice to replace it.")
    edited = st.data_editor(
        display_frame,
        hide_index=True,
        width="stretch",
        height=520,
        disabled=["ID"],
        column_config={
            "Delete": st.column_config.CheckboxColumn("Delete"),
            "ID": None,
            "Description": st.column_config.TextColumn("Description", required=True),
            "Date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
            "Amount": st.column_config.NumberColumn(
                "Amount", min_value=0.01, step=0.01, format="$%.2f", required=True
            ),
            **{
                column: st.column_config.MultiselectColumn(
                    column,
                    options=choice_options(database, config, kind),
                    accept_new_options=True,
                    required=column == "Category",
                    help="Choose one value. Type a new value and press Enter to confirm it.",
                )
                for column, kind in choice_columns.items()
            },
            "Type": st.column_config.SelectboxColumn(
                "Type",
                options=["expense", "refund", "income", "transfer"],
                required=True,
            ),
        },
        key=f"transaction_editor_{st.session_state.get('transaction_editor_generation', 0)}",
    )
    changes = []
    try:
        changes = collect_changes(display_frame, edited)
    except ValueError as exc:
        st.error(str(exc))
    review_column, discard_column = st.columns(2)
    if review_column.button(
        f"Review changes ({len(changes)})", type="primary", disabled=not changes
    ):
        _review_transaction_changes(database, changes)
    if discard_column.button("Discard edits / reload"):
        _reset_transaction_editor()
        st.rerun()


@st.dialog("Add a transaction", width="large")
def _add_transaction_dialog(database: Database, config: AppConfig) -> None:
    st.caption("Description and amount are required.")
    with st.form("add_transaction_form", clear_on_submit=True):
        left, right = st.columns(2)
        transaction_date = left.date_input("Date", value=date.today(), key="add_transaction_date")
        transaction_type = right.selectbox(
            "Type",
            ["expense", "refund", "income", "transfer"],
            key="add_transaction_type",
        )
        description = st.text_input(
            "Description",
            placeholder="What was this for?",
            key="add_transaction_description",
        )
        merchant = st.text_input(
            "Merchant",
            placeholder="Optional, improves recurring analysis",
            key="add_transaction_merchant",
        )
        left, right = st.columns(2)
        amount = left.number_input(
            "Amount",
            min_value=0.01,
            value=None,
            step=0.01,
            format="%.2f",
            placeholder="0.00",
            key="add_transaction_amount",
        )
        category = right.selectbox(
            "Category",
            _category_options(database, config),
            key="add_transaction_category",
            accept_new_options=True,
        )
        left, right = st.columns(2)
        account = left.selectbox(
            "Account",
            choice_options(database, config, "account"),
            index=(
                config.accounts.index(config.default_account)
                if config.default_account in config.accounts
                else 0
            ),
            key="add_transaction_account",
            accept_new_options=True,
        )
        payment_method = right.selectbox(
            "Payment method",
            choice_options(database, config, "payment_method"),
            index=(
                config.payment_methods.index(config.default_payment_method)
                if config.default_payment_method in config.payment_methods
                else 0
            ),
            key="add_transaction_payment_method",
            accept_new_options=True,
        )
        notes = st.text_area("Notes", height=80, key="add_transaction_notes")
        submitted = st.form_submit_button(
            "Save transaction",
            type="primary",
            key="add_transaction_submit",
        )
    if submitted:
        try:
            transaction_id = database.add_transaction(
                TransactionDraft(
                    transaction_date=transaction_date,
                    description=description,
                    amount_cents=parse_amount_cents(amount),
                    category=category,
                    account=account,
                    payment_method=payment_method,
                    merchant=merchant,
                    transaction_type=transaction_type,
                    notes=notes,
                )
            )
        except (ValueError, DuplicateTransactionError) as exc:
            st.error(str(exc))
        else:
            _invalidate_activity_filters()
            st.session_state["saved_transaction_id"] = transaction_id
            st.session_state["show_saved_transaction_notice"] = True
            st.rerun()


def _preview_table(preview: ImportPreview) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for row in preview.rows:
        draft = row.draft
        records.append(
            {
                "Row": row.row_number,
                "Status": ("Invalid" if row.errors else "Duplicate" if row.duplicate else "Ready"),
                "Date": draft.transaction_date if draft else None,
                "Description": draft.description if draft else "",
                "Amount": draft.amount_cents / 100 if draft else None,
                "Category": draft.category if draft else "",
                "Type": draft.transaction_type if draft else "",
                "Issue": "; ".join(row.errors),
            }
        )
    return pd.DataFrame(records)


def _render_import_export(
    database: Database, rows: list[dict[str, object]], config: AppConfig
) -> None:
    _page_heading(
        "LOCAL FILES",
        "Import and export",
        "Bring in statements or create a private backup without leaving this computer.",
    )
    st.html(
        """
        <div class="privacy-strip">
            <span class="privacy-dot"></span>
            Files are processed locally. Nothing is uploaded to a remote service.
        </div>
        """
    )

    _section_heading("Import a CSV", "Review every row before it is saved")
    uploaded = st.file_uploader("Choose a CSV", type=["csv"])
    import_bytes: bytes | None = uploaded.getvalue() if uploaded else None

    if import_bytes:
        preview = preview_csv(import_bytes, config, database.existing_fingerprints())
        ready = len(preview.valid_drafts)
        first, second, third = st.columns(3)
        first.metric("Ready", ready)
        second.metric("Duplicates", preview.duplicate_count)
        third.metric("Invalid", preview.invalid_count)
        st.dataframe(
            _preview_table(preview),
            hide_index=True,
            width="stretch",
            column_config={
                "Amount": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        if st.button(
            f"Import {ready} valid transaction(s)",
            type="primary",
            disabled=ready == 0,
        ):
            result = database.import_transactions(preview.valid_drafts)
            _invalidate_activity_filters()
            st.success(
                f"Imported {result.imported}; skipped {result.duplicates_skipped} duplicate(s)."
            )
            st.rerun()

    st.divider()
    _section_heading("Export a local backup", "Keep the downloaded file secure")
    st.caption("The exported CSV contains private spending data. Store it securely.")
    st.download_button(
        "Download transactions.csv",
        data=export_csv(rows),
        file_name=f"expenses-{date.today().isoformat()}.csv",
        mime="text/csv",
        disabled=not rows,
    )


def _render_budgets(database: Database, config: AppConfig) -> None:
    _page_heading(
        "YOUR SPENDING PLAN",
        "Budgets",
        "Monthly and quarterly allowance after committed costs.",
    )
    render_budget_page(database, config)


def _render_insights(database: Database, frame: pd.DataFrame) -> None:
    _page_heading(
        "DEEPER VIEW",
        "Advanced insights",
        "Patterns and exceptions to explore when you want more detail.",
    )
    if frame.empty:
        st.info("Add or import transactions to unlock insights.")
        return

    savings = savings_summary(frame)
    first, second, third = st.columns(3)
    with first:
        _kpi_card(
            "Recorded income",
            _currency(savings["income"] or 0.0),
            detail="In the selected range",
        )
    with second:
        _kpi_card(
            "Net outflow",
            _currency(savings["net_outflow"] or 0.0),
            detail="Expenses after refunds",
        )
    with third:
        _kpi_card(
            "Savings rate",
            (
                f"{float(savings['savings_rate']):.1f}%"
                if savings["savings_rate"] is not None
                else "Add income"
            ),
            detail="Based on recorded income",
        )

    _section_heading("What changed", "Category movement from the previous month")
    drivers = spending_drivers(frame)
    if drivers.empty:
        st.info("At least two months of data are needed.")
    else:
        st.dataframe(
            drivers.head(8),
            hide_index=True,
            width="stretch",
            column_config={
                "current": st.column_config.NumberColumn("Latest month", format="$%.2f"),
                "previous": st.column_config.NumberColumn("Previous month", format="$%.2f"),
                "change": st.column_config.NumberColumn("Change", format="$%.2f"),
                "percent_change": st.column_config.NumberColumn("Change %", format="%.1f%%"),
            },
        )

    left, right = st.columns(2)
    with left:
        _section_heading("Likely recurring charges", "Stable timing and amounts")
        recurring = recurring_transactions(frame)
        if recurring.empty:
            st.info("No stable recurring pattern detected yet.")
        else:
            st.dataframe(
                recurring,
                hide_index=True,
                width="stretch",
                column_config={
                    "average_amount": st.column_config.NumberColumn("Average", format="$%.2f"),
                    "median_interval_days": st.column_config.NumberColumn(
                        "Interval", format="%.0f days"
                    ),
                },
            )
    with right:
        _section_heading("Unusual purchases", "Large relative to their category")
        anomalies = spending_anomalies(frame)
        if anomalies.empty:
            st.info("No high-confidence anomalies detected.")
        else:
            st.dataframe(
                anomalies,
                hide_index=True,
                width="stretch",
                column_config={
                    "amount": st.column_config.NumberColumn(format="$%.2f"),
                    "typical_amount": st.column_config.NumberColumn("Typical", format="$%.2f"),
                    "anomaly_score": st.column_config.NumberColumn("Score", format="%.1f"),
                },
            )

    _section_heading("Cash flow", "Income, refunds, expenses, and the resulting balance")
    cash_flow = cash_flow_by_month(frame)
    if not cash_flow.empty:
        cash_flow["month_start"] = cash_flow["month"].dt.to_timestamp()
        chart = go.Figure()
        chart.add_bar(
            x=cash_flow["month_start"],
            y=cash_flow["income"] + cash_flow["refunds"],
            name="Income + refunds",
            marker_color=PRIMARY,
        )
        chart.add_bar(
            x=cash_flow["month_start"],
            y=-cash_flow["expenses"],
            name="Expenses",
            marker_color=CORAL,
        )
        chart.add_scatter(
            x=cash_flow["month_start"],
            y=cash_flow["net_cash_flow"],
            name="Net cash flow",
            mode="lines+markers",
            line={"color": GOLD, "width": 2.5},
        )
        chart.update_layout(barmode="relative")
        chart.update_yaxes(tickprefix="$")
        _plotly_chart(chart, key="cash_flow")

    _section_heading("Academic-period comparison", "A dynamic view of spending across terms")
    academic = academic_period_spending(frame)
    if not academic.empty:
        academic_chart = px.bar(
            academic,
            x="academic_period",
            y="spending",
            color="academic_year",
            text_auto="$.3s",
            labels={
                "academic_period": "Academic period",
                "spending": "Personal spending",
                "academic_year": "Academic year",
            },
            color_discrete_sequence=PALETTE,
        )
        academic_chart.update_yaxes(tickprefix="$")
        _plotly_chart(academic_chart, key="academic_periods")

    duplicate_groups = database.duplicate_groups()
    if duplicate_groups:
        st.warning(
            f"{len(duplicate_groups)} duplicate group(s) exist. "
            "Review them in Transactions before deleting anything."
        )


def _render_settings(database: Database, config: AppConfig) -> None:
    _page_heading(
        "PREFERENCES",
        "Settings and privacy",
        "Your data stays local, and your personal choices stay configurable.",
    )
    st.html(
        """
        <div class="privacy-hero">
            <span class="privacy-dot"></span>
            <div><strong>Local-only mode is active</strong>
            <span>The app is bound to this computer and telemetry is disabled.</span></div>
        </div>
        """
    )
    st.markdown(
        f"""
        - Database: `{DATABASE_PATH}`
        - Network binding: `127.0.0.1`
        - Streamlit telemetry: disabled
        - Private data and exports: ignored by Git
        - Transactions stored: `{database.count_transactions():,}`
        """
    )
    _section_heading("Local configuration", "Private defaults and calendar rules")
    st.write(
        "Copy `config.example.toml` to `config.toml` to customize categories, "
        "accounts, defaults, and the academic calendar. `config.toml` is ignored "
        "by Git, so personal account names remain local."
    )
    st.code("cp config.example.toml config.toml", language="bash")
    calendar_config = config.academic_calendar
    st.dataframe(
        pd.DataFrame(
            {
                "Period": ["Fall", "Winter", "Spring", "Summer"],
                "Months": [
                    ", ".join(map(str, calendar_config.fall_months)),
                    ", ".join(map(str, calendar_config.winter_months)),
                    ", ".join(map(str, calendar_config.spring_months)),
                    ", ".join(map(str, calendar_config.summer_months)),
                ],
            }
        ),
        hide_index=True,
        width="stretch",
    )
    if calendar_config.explicit_periods:
        st.caption("Explicit date ranges override the month-based fallback:")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Label": period.label,
                        "Start": period.start,
                        "End": period.end,
                    }
                    for period in calendar_config.explicit_periods
                ]
            ),
            hide_index=True,
            width="stretch",
        )


def _inject_styles() -> None:
    inject_theme()


def render_app() -> None:
    st.set_page_config(
        page_title="記帳",
        page_icon="▦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles()
    database = _database()
    config = load_config()

    st.html('<header class="masthead"><span class="wordmark" lang="zh-Hant">記帳</span></header>')

    page = st.sidebar.radio(
        "Navigate",
        [
            "Overview",
            "Transactions",
            "Import / Export",
            "Budgets",
            "Advanced insights",
            "Settings",
        ],
        label_visibility="collapsed",
        key="main_navigation",
    )
    st.sidebar.divider()
    with st.sidebar:
        st.html(
            """
            <div class="theme-control">
                <span class="theme-control-label">Appearance</span>
                <div class="theme-options" role="radiogroup" aria-label="Appearance">
                    <button type="button" role="radio" aria-checked="true"
                        data-jizhang-theme-choice="System">System</button>
                    <button type="button" role="radio" aria-checked="false"
                        data-jizhang-theme-choice="Light">Light</button>
                    <button type="button" role="radio" aria-checked="false"
                        data-jizhang-theme-choice="Dark">Dark</button>
                </div>
            </div>
            """
        )

    if page == "Budgets":
        _render_budgets(database, config)
        return
    if page == "Settings":
        _render_settings(database, config)
        return

    all_rows, rows, frame = _filtered_data(database, config)
    if page == "Overview":
        _render_dashboard(database, frame, all_rows)
    elif page == "Transactions":
        _render_transactions(database, frame, config)
    elif page == "Import / Export":
        _render_import_export(database, rows, config)
    elif page == "Advanced insights":
        _render_insights(database, frame)
