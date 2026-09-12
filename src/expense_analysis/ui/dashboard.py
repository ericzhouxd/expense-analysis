"""The Overview dashboard."""

from __future__ import annotations

import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ..analytics import (
    category_spending,
    comparable_year_months,
    monthly_spending,
    period_metrics,
    recurring_transactions,
    spending_anomalies,
    spending_drivers,
)
from ..database import Database
from ..spending_plan import calculate_plan
from .state import _render_empty_state
from .theme import CORAL, GOLD, MINT, PRIMARY, SAGE
from .widgets import (
    _currency,
    _kpi_card_markup,
    _page_heading,
    _percent_delta,
    _plotly_chart,
    _section_heading,
    _transaction_list,
)


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
