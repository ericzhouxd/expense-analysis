"""Overview: current spending, remaining allowance, and the next useful action."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..analytics import monthly_spending
from ..database import Database
from .spending import render_spending_summary
from .widgets import _currency, _page_heading, _plotly_chart, _section, _transaction_list


def _render_dashboard(
    database: Database, frame: pd.DataFrame, all_rows: list[dict[str, object]]
) -> None:
    _page_heading("OVERVIEW", "Overview")
    summary = render_spending_summary(database, key="overview")
    if frame.empty:
        st.info("Add or import transactions to start tracking your spending.")
        return
    month = summary["as_of"].strftime("%Y-%m")
    selected = frame[frame["month"].astype(str).eq(month)]
    left, right = st.columns([3, 2])
    with left:
        with _section(
            "category-breakdown",
            "Where this month’s money went",
            "All expense categories, after refunds",
        ):
            categories = (
                selected[selected["transaction_type"].isin(["expense", "refund"])]
                .groupby("category")["spending"]
                .sum()
                .reset_index()
            )
            if categories.empty:
                st.info("No expenses recorded for this month yet.")
            else:
                chart = px.bar(
                    categories.sort_values("spending"), x="spending", y="category", orientation="h"
                )
                chart.update_xaxes(tickprefix="$")
                _plotly_chart(chart, key="category_breakdown", height=320)
    with right:
        with _section("worth-checking", "Worth checking"):
            if summary["active"]:
                st.write(
                    f"Unpaid planned bills: {_currency(summary['unpaid'] / 100)}. "
                    f"Already protected in your available amount."
                )
                if summary["available"] < 0:
                    st.warning(
                        "Spending, commitments and buffer exceed the current pool. Review "
                        "the pool or planned costs in Budgets."
                    )
                elif summary["month_available"] < 0:
                    st.info(
                        "You are ahead of the monthly spending pace. Your remaining "
                        "school-year pool is shown above."
                    )
            unknown = selected[selected["category"].eq("Uncategorized")]
            if not unknown.empty:
                st.write(
                    f"{len(unknown)} uncategorized transaction(s). Check whether any "
                    f"should match a planned bill."
                )
            prior = summary["previous_year_month"]
            if prior is not None:
                st.write(
                    f"Same point last year: {_currency(prior / 100)}. Difference: "
                    f"{_currency((summary['month_spent'] - prior) / 100)}."
                )
            st.caption(
                "Budgets explains the allowance and bill reserves. Advanced "
                "insights compares spending pace and previous school years."
            )
    with _section(
        "spending-by-month",
        "Spending by month",
        "Includes bills and everyday purchases; refunds reduce spending",
    ):
        monthly = monthly_spending(frame, personal_only=False)
        if not monthly.empty:
            monthly = monthly.copy()
            monthly["label"] = monthly["month"].astype(str)
            chart = px.bar(
                monthly.tail(12),
                x="label",
                y="spending",
                labels={"label": "Month", "spending": "Net spent"},
            )
            chart.update_yaxes(tickprefix="$")
            _plotly_chart(chart, key="spending_trend", height=280)
    with _section(
        "recent-activity", "Recent activity", "Latest transactions in the reporting month"
    ):
        _transaction_list(selected, limit=6)
