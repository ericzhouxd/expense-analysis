"""Shared as-of-date spending views, independent of UI filters."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .models import comparable_day, month_after
from .spending_treatment import TREATMENTS, classify_spending
from .term_budget import BudgetSettings


def net_spending(rows: list[dict[str, Any]], start: date, end: date) -> int:
    return sum(
        int(row["amount_cents"]) * (-1 if row["transaction_type"] == "refund" else 1)
        for row in rows
        if row["transaction_type"] in ("expense", "refund")
        and start.isoformat() <= str(row["transaction_date"])[:10] <= end.isoformat()
    )


def previous_year(day: date, years: int = 1) -> date:
    """The comparable date ``years`` earlier; a month's last day maps to a month end."""
    year = day.year - years
    return date(year, day.month, comparable_day(day, year, day.month))


def comparison(
    rows: list[dict[str, Any]], start: date, end: date, prior_start: date, prior_end: date
) -> dict:
    current = net_spending(rows, start, end)
    known = any(
        prior_start.isoformat() <= str(r["transaction_date"])[:10] <= prior_end.isoformat()
        for r in rows
    )
    previous = net_spending(rows, prior_start, prior_end) if known else None
    delta = current - previous if previous is not None else None
    return {
        "current": current,
        "previous": previous,
        "change": delta,
        "percent": delta / abs(previous) * 100 if previous and delta is not None else None,
        "start": start,
        "end": end,
        "prior_start": prior_start,
        "prior_end": prior_end,
    }


def spending_summary(
    budget: BudgetSettings | None,
    rows: list[dict[str, Any]],
    as_of: date,
    rules: dict | None = None,
) -> dict[str, Any]:
    rows = classify_spending(rows, budget, rules)
    everyday = [r for r in rows if r["spending_treatment"] == "Everyday"]
    start = as_of.replace(day=1)
    result: dict[str, Any] = {
        "as_of": as_of,
        "month_spent": net_spending(rows, start, as_of),
        "previous_year_month": None,
    }
    prior_start, prior_end = previous_year(start), previous_year(as_of)
    if any(
        prior_start.isoformat() <= str(r["transaction_date"])[:10] <= prior_end.isoformat()
        for r in rows
    ):
        result["previous_year_month"] = net_spending(rows, prior_start, prior_end)
    prior_month = month_after(start, -1)
    prior_month_end = prior_month.replace(
        day=comparable_day(as_of, prior_month.year, prior_month.month)
    )
    week_start = as_of - timedelta(days=as_of.weekday())
    result.update(
        everyday_spent=net_spending(everyday, start, as_of),
        treatment_totals={
            t: net_spending([r for r in rows if r["spending_treatment"] == t], start, as_of)
            for t in TREATMENTS
        },
        review_count=sum(
            r["treatment_review"]
            for r in rows
            if r["transaction_type"] in ("expense", "refund")
            and start.isoformat() <= str(r["transaction_date"])[:10] <= as_of.isoformat()
        ),
        everyday_month_comparison=comparison(everyday, start, as_of, prior_month, prior_month_end),
        everyday_week_comparison=comparison(
            everyday, week_start, as_of, week_start - timedelta(days=7), as_of - timedelta(days=7)
        ),
        everyday_year_comparison=comparison(everyday, start, as_of, prior_start, prior_end),
    )
    return result
