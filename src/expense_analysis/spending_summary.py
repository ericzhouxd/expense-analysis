"""Shared as-of-date spending views, independent of UI filters and Streamlit."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from .spending_plan import SpendingPlan, calculate_plan, month_after


def net_spending(rows: list[dict[str, Any]], start: date, end: date) -> int:
    return sum(
        int(row["amount_cents"]) * (-1 if row["transaction_type"] == "refund" else 1)
        for row in rows
        if row["transaction_type"] in ("expense", "refund")
        and start.isoformat() <= str(row["transaction_date"])[:10] <= end.isoformat()
    )


def previous_year(day: date, years: int = 1) -> date:
    year = day.year - years
    return date(year, day.month, min(day.day, monthrange(year, day.month)[1]))


def spending_summary(
    plan: SpendingPlan | None, rows: list[dict[str, Any]], as_of: date
) -> dict[str, Any]:
    start = as_of.replace(day=1)
    end = month_after(start, 1)
    result: dict[str, Any] = {
        "as_of": as_of,
        "month_spent": net_spending(rows, start, as_of),
        "previous_year_month": None,
        "active": False,
    }
    prior_start, prior_end = previous_year(start), previous_year(as_of)
    if any(
        prior_start.isoformat() <= str(r["transaction_date"])[:10] <= prior_end.isoformat()
        for r in rows
    ):
        result["previous_year_month"] = net_spending(rows, prior_start, prior_end)
    if plan is None:
        return result
    plan_end = month_after(plan.start, plan.months)
    academic_end = month_after(plan.start, 9)
    actuals = [r for r in rows if str(r["transaction_date"])[:10] <= as_of.isoformat()]
    calculated = calculate_plan(plan, actuals)
    result.update(
        plan=calculated,
        pool=plan.total_target_cents,
        buffer=plan.buffer_cents,
        year_spent=sum(r["net_cents"] for r in calculated["transactions"]),
        unpaid=sum(b["unpaid"] for b in calculated["obligations"]),
    )
    result["available"] = (
        result["pool"] - result["year_spent"] - result["unpaid"] - result["buffer"]
    )
    result["benchmark"] = sum(plan.reference.get("components", {}).values())
    index = (as_of.year - plan.start.year) * 12 + as_of.month - plan.start.month
    if not 0 <= index < plan.months:
        return result
    month, quarter = calculated["months"][index], calculated["quarters"][index // 3]
    quarter_start = month_after(plan.start, index // 3 * 3)
    quarter_end = month_after(quarter_start, 3)
    elapsed = (as_of - quarter_start).days + 1
    quarter_spent = sum(
        r["net_cents"] for r in calculated["transactions"] if r["budget_month"] in quarter["months"]
    )
    flexible_rate = quarter["flexible_spent"] / elapsed
    result.update(
        active=True,
        month=month,
        quarter=quarter,
        quarter_spent=quarter_spent,
        month_available=min(month["remaining"], result["available"]),
        quarter_available=min(quarter["remaining"], result["available"]),
        projected_quarter=quarter["reserved"]
        + quarter["flexible_spent"]
        + round(flexible_rate * max(0, (quarter_end - as_of).days - 1)),
        projected_year=sum(b["reserved"] for b in calculated["obligations"])
        + sum(m["flexible_spent"] for m in calculated["months"])
        + round(flexible_rate * max(0, (plan_end - as_of).days - 1)),
    )
    result["weekly_guide"] = round(
        max(0, result["month_available"]) * min(7, (end - as_of).days) / (end - as_of).days
    )
    academic_actual = sum(
        r["net_cents"]
        for r in calculated["transactions"]
        if r["budget_month"] < academic_end.strftime("%Y-%m")
    )
    result["academic_spent"] = academic_actual
    elapsed_academic = min(max((as_of - plan.start).days + 1, 0), (academic_end - plan.start).days)
    result["benchmark_pace"] = round(
        result["benchmark"] * elapsed_academic / (academic_end - plan.start).days
    )
    result["year_comparisons"] = []
    earliest = min((str(r["transaction_date"])[:10] for r in rows), default=None)
    offset = 1
    while earliest is not None and offset <= 50:
        first, last = previous_year(plan.start, offset), previous_year(as_of, offset)
        if last.isoformat() < earliest:
            break
        if any(
            first.isoformat() <= str(r["transaction_date"])[:10] <= last.isoformat() for r in rows
        ):
            start_year = plan.start.year - offset
            result["year_comparisons"].append(
                {
                    "School year": f"{start_year}–{start_year + 1}",
                    "Net spent": net_spending(rows, first, last) / 100,
                }
            )
        offset += 1
    return result
