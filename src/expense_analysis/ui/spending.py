"""One consistent spending summary used by the three planning pages."""

from datetime import date

import pandas as pd
import streamlit as st

from ..database import Database
from ..spending_plan import month_after
from ..spending_summary import spending_summary
from .widgets import _currency, _kpi_card_markup, _section_heading


def render_spending_summary(database: Database, *, key: str, details: bool = False) -> dict:
    rows = database.list_transactions()
    plan = database.get_spending_plan()
    today = date.today()
    options = sorted(
        {
            today.strftime("%Y-%m"),
            *(str(r["transaction_date"])[:7] for r in rows),
            *(plan.month_keys if plan else []),
        }
    )
    options = [m for m in options if m <= today.strftime("%Y-%m")]
    month = st.selectbox(
        "Reporting month",
        options,
        index=options.index(today.strftime("%Y-%m")),
        key=f"{key}_report_month",
    )
    first = date.fromisoformat(month + "-01")
    from datetime import timedelta

    as_of = min(today, month_after(first, 1) - timedelta(days=1))
    summary = spending_summary(plan, rows, as_of)
    st.caption(
        f"Through {as_of:%b %d, %Y} · full ledger · expenses minus refunds · transfers excluded"
    )
    cards = [("Spent this month", summary["month_spent"], "Actual transaction dates")]
    if summary["active"]:
        cards += [
            (
                "Rest of month",
                summary["month_available"],
                "Paced allowance + carryover; bills and buffer protected",
            ),
            (
                "Rest of quarter",
                summary["quarter_available"],
                "Includes carry from earlier quarters",
            ),
            (
                "School-year available",
                summary["available"],
                "Whole pool after spending, unpaid bills and buffer",
            ),
        ]
    else:
        prior = summary["previous_year_month"]
        if prior is not None:
            cards.append(("Same point last year", prior, "Same month through the same day"))
    st.html(
        '<div class="kpi-grid">'
        + "".join(
            _kpi_card_markup(label, _currency(value / 100), detail=detail, featured=i == 0)
            for i, (label, value, detail) in enumerate(cards)
        )
        + "</div>"
    )
    if not plan:
        st.info(
            "Set a school-year pool and committed costs in Budgets to see what remains after bills."
        )
        return summary
    if not summary["active"]:
        st.info(
            "This reporting month is outside the saved plan. Choose a month within its coverage."
        )
        return summary
    st.caption(
        f"Weekly guide for the rest of this month: {_currency(summary['weekly_guide'] / 100)}. "
        "A planning guide, not a hard spending limit or a bank balance."
    )
    if details:
        _section_heading(
            "School-year pool", "Paid bills replace reserves; they are never deducted twice"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Item": label, "Amount": _currency(summary[field] / 100)}
                    for label, field in [
                        ("Starting pool", "pool"),
                        ("Spent so far", "year_spent"),
                        ("Unpaid commitments", "unpaid"),
                        ("Protected buffer", "buffer"),
                        ("Available after commitments", "available"),
                    ]
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        _section_heading(
            "Pace and comparisons", "Benchmarks are reference points, not spending limits"
        )
        a, b, c = st.columns(3)
        a.metric("Quarter spending so far", _currency(summary["quarter_spent"] / 100))
        b.metric("Quarter-end outlook", _currency(summary["projected_quarter"] / 100))
        c.metric("School-year outlook", _currency(summary["projected_year"] / 100))
        st.caption(
            "Outlooks keep planned bill reserves and extend this quarter’s "
            "daily everyday spending pace. Early-quarter estimates can be "
            "noisy."
        )
        if summary["benchmark"]:
            st.write(
                f"Academic-year spending: {_currency(summary['academic_spent'] / 100)} · "
                f"UCLA reference through this point: "
                f"{_currency(summary['benchmark_pace'] / 100)} · "
                f"Full nine-month reference: {_currency(summary['benchmark'] / 100)}."
            )
            st.caption(
                f"Saved {plan.reference.get('year', '')} UCLA reference, spread "
                f"evenly over nine months for comparison; actual tuition and housing "
                f"payments are uneven. Summer is excluded from this comparison."
            )
        if summary["year_comparisons"]:
            st.dataframe(
                pd.DataFrame(summary["year_comparisons"]),
                hide_index=True,
                width="stretch",
                column_config={"Net spent": st.column_config.NumberColumn(format="$%.2f")},
            )
            st.caption(
                "Previous school years use the same start month through the same "
                "calendar day, using original transaction dates. Missing records "
                "are not estimated; payment allocations may affect comparability."
            )
        else:
            st.caption("No previous-school-year records for this comparable date range yet.")
    return summary
