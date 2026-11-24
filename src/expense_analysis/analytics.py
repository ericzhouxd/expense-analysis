from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .config import AppConfig
from .models import comparable_day, normalize_text

# Weight of the newest month in the forecast's running level; each older month
# counts 60% as much as the one after it.
FORECAST_SMOOTHING = 0.4
FORECAST_MINIMUM_MONTHS = 2
# A kind of day (quarter, break, summer) needs about a week of history
# before its own rate counts as much as the overall average.
FORECAST_SHRINK_DAYS = 7
AVERAGE_MONTH_DAYS = 365.25 / 12
# A repeat purchase counts half as much toward what is offered first after two months.
FREQUENT_HALF_LIFE_DAYS = 60
# How far back the largest purchases reach while a month is still going.
LARGEST_DAYS = 30
FORECAST_COLUMNS = ("month", "expected", "low", "high", "spent", "partial")

TRANSACTION_COLUMNS = (
    "id",
    "transaction_date",
    "description",
    "amount_cents",
    "category",
    "account",
    "payment_method",
    "merchant",
    "transaction_type",
    "notes",
    "fingerprint",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class PeriodMetrics:
    period_label: str
    spending: float
    previous_period_spending: float
    previous_year_spending: float
    change_from_previous: float | None
    change_from_previous_year: float | None
    monthly_average: float
    projected_month_end: float
    is_partial: bool


@dataclass(frozen=True)
class SpendingForecast:
    """Projected net spending by month, in dollars.

    ``level`` is the typical month the forecast starts from and ``typical_miss`` is
    how far this method was off, on average, when replayed over the months already
    recorded. ``months`` is empty until there is enough history.
    """

    level: float
    typical_miss: float | None
    history_months: int
    months: pd.DataFrame
    # What a week of each kind of day (quarter, break, summer) costs, when the
    # forecast was given a calendar.
    weekly_rates: dict[str, float] = field(default_factory=dict)


def _percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous * 100


def transactions_frame(rows: list[dict[str, object]], config: AppConfig) -> pd.DataFrame:
    if not rows:
        frame = pd.DataFrame(columns=TRANSACTION_COLUMNS)
        frame["transaction_date"] = pd.to_datetime(frame["transaction_date"])
        for column in ("amount", "spending", "cash_flow"):
            frame[column] = pd.Series(dtype=float)
        return frame

    frame = pd.DataFrame(rows)
    frame["transaction_date"] = pd.to_datetime(frame["transaction_date"], errors="coerce")
    frame = frame.dropna(subset=["transaction_date", "amount_cents"]).copy()
    frame["amount"] = frame["amount_cents"].astype(float) / 100
    frame["spending"] = np.select(
        [
            frame["transaction_type"].eq("expense"),
            frame["transaction_type"].eq("refund"),
        ],
        [frame["amount"], -frame["amount"]],
        default=0.0,
    )
    frame["cash_flow"] = np.select(
        [
            frame["transaction_type"].eq("expense"),
            frame["transaction_type"].isin(["refund", "income"]),
        ],
        [-frame["amount"], frame["amount"]],
        default=0.0,
    )
    frame["spending_class"] = frame["category"].map(config.spending_class)
    frame["month"] = frame["transaction_date"].dt.to_period("M")
    frame["year"] = frame["transaction_date"].dt.year
    frame["month_number"] = frame["transaction_date"].dt.month
    frame["academic_period"] = frame["transaction_date"].map(
        lambda value: config.academic_calendar.label_for(value.date())
    )
    frame["academic_year"] = frame["transaction_date"].map(
        lambda value: (
            f"{value.year}-{str(value.year + 1)[-2:]}"
            if value.month >= min(config.academic_calendar.fall_months)
            else f"{value.year - 1}-{str(value.year)[-2:]}"
        )
    )
    return frame


def spending_frame(frame: pd.DataFrame, *, personal_only: bool = False) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    spending = frame[frame["transaction_type"].isin(["expense", "refund"])].copy()
    if personal_only:
        spending = spending[spending["spending_class"].eq("Personal")]
    return spending


def monthly_spending(
    frame: pd.DataFrame, *, personal_only: bool = False, through: date | None = None
) -> pd.DataFrame:
    """Net spending per month with rolling averages; quiet months count as zero.

    ``through`` extends the months to that date's month, so a month with nothing
    spent yet still appears.
    """
    spending = spending_frame(frame, personal_only=personal_only)
    columns = ["month", "spending", "rolling_3", "rolling_6", "rolling_12"]
    if spending.empty:
        return pd.DataFrame(columns=columns)

    grouped = spending.groupby("month", as_index=True)["spending"].sum().sort_index()
    last = grouped.index.max()
    if through is not None:
        last = max(last, pd.Period(through, freq="M"))
    full_index = pd.period_range(grouped.index.min(), last, freq="M")
    grouped = grouped.reindex(full_index, fill_value=0.0)
    result = grouped.rename_axis("month").reset_index()
    for window in (3, 6, 12):
        result[f"rolling_{window}"] = result["spending"].rolling(window, min_periods=1).mean()
    return result


def category_spending(frame: pd.DataFrame, *, personal_only: bool = False) -> pd.DataFrame:
    spending = spending_frame(frame, personal_only=personal_only)
    if spending.empty:
        return pd.DataFrame(columns=["category", "spending"])
    grouped = spending.groupby("category")["spending"].sum().reset_index()
    return grouped.sort_values("spending", ascending=False)


def period_metrics(
    frame: pd.DataFrame,
    as_of: date | None = None,
    *,
    personal_only: bool = False,
) -> PeriodMetrics:
    spending = spending_frame(frame, personal_only=personal_only)
    if spending.empty:
        empty_date = as_of or date.today()
        return PeriodMetrics(
            period_label=empty_date.strftime("%B %Y"),
            spending=0,
            previous_period_spending=0,
            previous_year_spending=0,
            change_from_previous=None,
            change_from_previous_year=None,
            monthly_average=0,
            projected_month_end=0,
            is_partial=empty_date.day < calendar.monthrange(empty_date.year, empty_date.month)[1],
        )

    latest_data_date = spending["transaction_date"].max().date()
    if as_of is None:
        today = date.today()
        if (latest_data_date.year, latest_data_date.month) == (
            today.year,
            today.month,
        ):
            as_of = today
        else:
            last_day = calendar.monthrange(latest_data_date.year, latest_data_date.month)[1]
            as_of = latest_data_date.replace(day=last_day)
    month_start = pd.Timestamp(as_of.replace(day=1))
    cutoff = pd.Timestamp(as_of)
    days_elapsed = as_of.day
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]

    current = spending[spending["transaction_date"].between(month_start, cutoff)]["spending"].sum()

    previous_month_start = month_start - pd.offsets.MonthBegin(1)
    previous_month_cutoff = previous_month_start.replace(
        day=comparable_day(as_of, previous_month_start.year, previous_month_start.month)
    )
    previous = spending[
        spending["transaction_date"].between(previous_month_start, previous_month_cutoff)
    ]["spending"].sum()

    prior_year_start = month_start - pd.DateOffset(years=1)
    prior_year_cutoff = prior_year_start.replace(
        day=comparable_day(as_of, prior_year_start.year, prior_year_start.month)
    )
    previous_year = spending[
        spending["transaction_date"].between(prior_year_start, prior_year_cutoff)
    ]["spending"].sum()

    monthly = monthly_spending(frame, personal_only=personal_only)
    monthly_average = float(monthly["spending"].mean()) if not monthly.empty else 0
    is_partial = days_elapsed < days_in_month
    projected = current / days_elapsed * days_in_month if is_partial and days_elapsed else current
    return PeriodMetrics(
        period_label=as_of.strftime("%B %Y"),
        spending=float(current),
        previous_period_spending=float(previous),
        previous_year_spending=float(previous_year),
        change_from_previous=_percent_change(float(current), float(previous)),
        change_from_previous_year=_percent_change(float(current), float(previous_year)),
        monthly_average=monthly_average,
        projected_month_end=float(projected),
        is_partial=is_partial,
    )


def weekly_spending(frame: pd.DataFrame, *, through: date | None = None) -> pd.DataFrame:
    """Net spending per Monday-to-Sunday week with a four-week rolling average.

    ``week`` is the Monday. Quiet weeks count as zero and ``through`` extends the
    weeks to that date's week, the same way ``monthly_spending`` treats months.
    """
    spending = spending_frame(frame)
    columns = ["week", "spending", "rolling_4"]
    if spending.empty:
        return pd.DataFrame(columns=columns)

    weeks = spending["transaction_date"].dt.to_period("W-SUN")
    grouped = spending.groupby(weeks)["spending"].sum().sort_index()
    last = grouped.index.max()
    if through is not None:
        last = max(last, pd.Period(through, freq="W-SUN"))
    full_index = pd.period_range(grouped.index.min(), last, freq="W-SUN")
    result = grouped.reindex(full_index, fill_value=0.0).rename_axis("week").reset_index()
    result["week"] = result["week"].map(lambda week: week.start_time.date())
    result["rolling_4"] = result["spending"].rolling(4, min_periods=1).mean()
    return result


def _kind_factors(daily: pd.Series, kinds: pd.Series) -> dict[str, float]:
    """How a day of each kind (quarter, break, summer) compares with the average day.

    A kind seen on few days is pulled toward 1 so it cannot swing the forecast.
    """
    overall = float(daily.mean()) if len(daily) else 0.0
    if overall <= 0:
        return {}
    factors = {}
    for kind, values in daily.groupby(kinds):
        ratio = max(0.0, float(values.mean()) / overall)
        days = len(values)
        factors[str(kind)] = (days * ratio + FORECAST_SHRINK_DAYS) / (days + FORECAST_SHRINK_DAYS)
    return factors


def _day_weights(kinds: pd.Series, factors: dict[str, float]) -> pd.Series:
    """Each day's factor; days of an unknown kind count as average."""
    return kinds.map(factors).fillna(1.0).astype(float)


def _month_mix(kinds: pd.Series, factors: dict[str, float]) -> pd.Series:
    """The average factor of each month's days: 1 for an ordinary month."""
    weights = _day_weights(kinds, factors)
    return weights.groupby(pd.DatetimeIndex(weights.index).to_period("M")).mean()


def _typical_month(history: pd.Series, mix: pd.Series) -> float:
    """Recent months count more, each first scaled to what an ordinary month would cost."""
    adjusted = history / mix.reindex(history.index)
    return max(0.0, float(adjusted.ewm(alpha=FORECAST_SMOOTHING, adjust=True).mean().iloc[-1]))


def spending_forecast(
    frame: pd.DataFrame,
    as_of: date,
    *,
    horizon: int = 3,
    kind_of: Callable[[date], str | None] | None = None,
) -> SpendingForecast:
    """Project the rest of ``as_of``'s month and the ``horizon`` months after it.

    The typical month is an exponentially weighted average of the complete months,
    so recent months count more. ``kind_of`` names the kind of each day on the
    school calendar (quarter, break, summer). When given, the forecast learns how
    much a day of each kind costs against the average day, and a month is the
    typical month scaled by the mix of its days.

    The range comes from replaying the forecast over the recorded months, each
    predicted only from what came before it, and averaging how far it missed; it
    widens for months further out. A month in progress keeps what is already
    spent and adds the remaining days at a rate that moves from the typical month
    to this month's own pace as the month goes on.
    """
    empty = pd.DataFrame(columns=list(FORECAST_COLUMNS))
    spending = spending_frame(frame)
    if not spending.empty:
        spending = spending[spending["transaction_date"] <= pd.Timestamp(as_of)]
    if spending.empty:
        return SpendingForecast(0.0, None, 0, empty)

    current = pd.Period(as_of, freq="M")
    partial = as_of.day < current.days_in_month
    totals = spending.groupby("month")["spending"].sum()
    first = spending["transaction_date"].min()
    start = first.to_period("M")
    # A ledger that starts mid-month would make its first month look cheap.
    if first.day > 7:
        start += 1
    last_complete = current - 1 if partial else current
    history = totals.reindex(pd.period_range(start, last_complete, freq="M"), fill_value=0.0)
    spent = float(totals.get(current, 0.0)) if partial else 0.0
    if len(history) < FORECAST_MINIMUM_MONTHS:
        return SpendingForecast(0.0, None, len(history), empty)

    # Every day from the first month of history to the last month forecast.
    days = pd.date_range(
        start.start_time, (current + horizon + 1).start_time, freq="D", inclusive="left"
    )
    kinds = pd.Series(
        [kind_of(day.date()) if kind_of else None for day in days], index=days, dtype=object
    )
    daily = (
        spending.groupby(spending["transaction_date"].dt.normalize())["spending"]
        .sum()
        .reindex(days, fill_value=0.0)
    )

    # Each month is compared with the forecast made only from the days before it.
    misses = []
    for at in range(1, len(history)):
        month = history.index[at]
        before = days < month.start_time
        seen = _kind_factors(daily[before], kinds[before])
        mix = _month_mix(kinds, seen)
        guess = _typical_month(history.iloc[:at], mix) * float(mix.get(month, 1.0))
        misses.append(abs(float(history.iloc[at]) - guess))
    miss = float(np.mean(misses))

    recorded = days < (last_complete + 1).start_time
    factors = _kind_factors(daily[recorded], kinds[recorded])
    mix = _month_mix(kinds, factors)
    level = _typical_month(history, mix)

    rows: list[dict[str, object]] = []
    if partial:
        weights = _day_weights(kinds[days.to_period("M") == current], factors)
        today = pd.Timestamp(as_of)
        ahead = float(weights[weights.index > today].mean())
        behind = float(weights[weights.index <= today].mean())
        left = (current.days_in_month - as_of.day) / current.days_in_month
        expected = spent + left * spent * ahead / behind + left * left * level * ahead
        band = miss * left**0.5 * ahead
        rows.append(
            {
                "month": current,
                "expected": expected,
                "low": min(expected, max(spent, expected - band)),
                "high": expected + band,
                "spent": spent,
                "partial": True,
            }
        )
    for step in range(1, horizon + 1):
        scale = float(mix.get(current + step, 1.0))
        band = miss * scale * (1 + (step - 1) * FORECAST_SMOOTHING**2) ** 0.5
        rows.append(
            {
                "month": current + step,
                "expected": level * scale,
                "low": max(0.0, level * scale - band),
                "high": level * scale + band,
                "spent": 0.0,
                "partial": False,
            }
        )
    return SpendingForecast(
        level,
        miss,
        len(history),
        pd.DataFrame(rows, columns=list(FORECAST_COLUMNS)),
        {kind: level * factor * 7 / AVERAGE_MONTH_DAYS for kind, factor in factors.items()},
    )


def comparable_year_months(frame: pd.DataFrame) -> pd.DataFrame:
    spending = spending_frame(frame, personal_only=True)
    if spending.empty:
        return pd.DataFrame(columns=["year", "month_number", "spending"])
    grouped = spending.groupby(["year", "month_number"])["spending"].sum().reset_index()
    return grouped.sort_values(["year", "month_number"])


def academic_period_spending(frame: pd.DataFrame, *, personal_only: bool = True) -> pd.DataFrame:
    spending = spending_frame(frame, personal_only=personal_only)
    if spending.empty:
        return pd.DataFrame(columns=["academic_period", "academic_year", "spending", "first_date"])
    return (
        spending.groupby(["academic_period", "academic_year"], as_index=False)
        .agg(spending=("spending", "sum"), first_date=("transaction_date", "min"))
        .sort_values("first_date")
    )


def cash_flow_by_month(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["month", "income", "expenses", "refunds", "net_cash_flow"])
    working = frame.copy()
    working["income"] = np.where(working["transaction_type"].eq("income"), working["amount"], 0.0)
    working["expenses"] = np.where(
        working["transaction_type"].eq("expense"), working["amount"], 0.0
    )
    working["refunds"] = np.where(working["transaction_type"].eq("refund"), working["amount"], 0.0)
    grouped = (
        working.groupby("month", as_index=False)[["income", "expenses", "refunds"]]
        .sum()
        .sort_values("month")
    )
    grouped["net_cash_flow"] = grouped["income"] + grouped["refunds"] - grouped["expenses"]
    return grouped


def spending_drivers(frame: pd.DataFrame, as_of: date | None = None) -> pd.DataFrame:
    spending = spending_frame(frame)
    if spending.empty:
        return pd.DataFrame(columns=["category", "current", "previous", "change", "percent_change"])
    as_of = as_of or spending["transaction_date"].max().date()
    current_period = pd.Period(as_of, freq="M")
    previous_period = current_period - 1
    if not spending["month"].isin([previous_period]).any():
        return pd.DataFrame(columns=["category", "current", "previous", "change", "percent_change"])
    # The reporting month runs through as_of; the previous month through its
    # comparable day, or in full when the reporting month is complete.
    day = spending["transaction_date"].dt.day
    previous_last = comparable_day(as_of, previous_period.year, previous_period.month)
    spending = spending[
        (spending["month"].isin([current_period]) & day.le(as_of.day))
        | (spending["month"].isin([previous_period]) & day.le(previous_last))
    ]
    grouped = spending.groupby(["category", "month"])["spending"].sum().unstack(fill_value=0)
    for period in (current_period, previous_period):
        if period not in grouped.columns:
            grouped[period] = 0.0
    result = pd.DataFrame(
        {
            "category": grouped.index,
            "current": grouped[current_period].values,
            "previous": grouped[previous_period].values,
        }
    )
    result["change"] = result["current"] - result["previous"]
    result["percent_change"] = np.where(
        result["previous"] != 0,
        result["change"] / result["previous"].abs() * 100,
        np.nan,
    )
    return result.sort_values("change", ascending=False)


# (label, shortest, longest) median gap in days for each recognised billing cycle.
def savings_summary(frame: pd.DataFrame) -> dict[str, float | None]:
    if frame.empty:
        return {"income": 0.0, "net_outflow": 0.0, "savings": 0.0, "savings_rate": None}
    income = float(frame.loc[frame["transaction_type"].eq("income"), "amount"].sum())
    expenses = float(frame.loc[frame["transaction_type"].eq("expense"), "amount"].sum())
    refunds = float(frame.loc[frame["transaction_type"].eq("refund"), "amount"].sum())
    net_outflow = expenses - refunds
    savings = income - net_outflow
    savings_rate = savings / income * 100 if income else None
    return {
        "income": income,
        "net_outflow": net_outflow,
        "savings": savings,
        "savings_rate": savings_rate,
    }


def frequent_entries(
    rows: list[dict[str, Any]], as_of: date, limit: int = 40
) -> list[dict[str, Any]]:
    """Purchases made more than once, the likeliest to be made again first.

    Each carries how it was last recorded, so it can be logged again without
    typing it out. Recent purchases weigh more than old ones.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = date.fromisoformat(str(row["transaction_date"])[:10])
        key = normalize_text(str(row["description"]))
        if row["transaction_type"] == "expense" and key and day <= as_of:
            groups.setdefault(key, []).append({**row, "day": day})
    ranked = []
    for items in groups.values():
        if len(items) < 2:
            continue
        score = sum(0.5 ** ((as_of - item["day"]).days / FREQUENT_HALF_LIFE_DAYS) for item in items)
        latest = max(items, key=lambda item: (item["day"], str(item.get("created_at") or "")))
        ranked.append((score, latest, len(items)))
    ranked.sort(key=lambda item: (-item[0], str(item[1]["description"])))
    return [
        {
            "description": latest["description"],
            "merchant": latest["merchant"],
            "amount_cents": int(latest["amount_cents"]),
            "category": latest["category"],
            "account": latest["account"],
            "payment_method": latest["payment_method"],
            "count": count,
            "last": latest["day"],
        }
        for _, latest, count in ranked[:limit]
    ]


def largest_purchases(
    rows: list[dict[str, Any]], start: date, end: date, limit: int = 6
) -> list[dict[str, Any]]:
    """The largest purchases from ``start`` through ``end``, bills left out.

    ``rows`` are classified spending. Refunds are not purchases. The more recent
    of two equal amounts comes first.
    """
    found = [
        row
        for row in rows
        if row["transaction_type"] == "expense"
        and row["spending_treatment"] != "Commitments"
        and start.isoformat() <= str(row["transaction_date"])[:10] <= end.isoformat()
    ]
    found.sort(key=lambda row: str(row["transaction_date"])[:10], reverse=True)
    found.sort(key=lambda row: -int(row["amount_cents"]))
    return found[:limit]
