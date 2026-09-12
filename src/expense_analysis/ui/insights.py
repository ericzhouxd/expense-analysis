"""The Advanced insights page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ..analytics import (
    academic_period_spending,
    cash_flow_by_month,
    recurring_transactions,
    savings_summary,
    spending_anomalies,
    spending_drivers,
)
from ..database import Database
from .theme import CORAL, GOLD, PALETTE, PRIMARY
from .widgets import (
    _currency,
    _kpi_card,
    _page_heading,
    _plotly_chart,
    _section_heading,
)


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
