from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .config import AppConfig

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


def monthly_spending(frame: pd.DataFrame, *, personal_only: bool = False) -> pd.DataFrame:
    spending = spending_frame(frame, personal_only=personal_only)
    columns = ["month", "spending", "rolling_3", "rolling_6", "rolling_12"]
    if spending.empty:
        return pd.DataFrame(columns=columns)

    grouped = spending.groupby("month", as_index=True)["spending"].sum().sort_index()
    full_index = pd.period_range(grouped.index.min(), grouped.index.max(), freq="M")
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
    previous_month_last = calendar.monthrange(
        previous_month_start.year, previous_month_start.month
    )[1]
    previous_month_cutoff = previous_month_start.replace(day=min(days_elapsed, previous_month_last))
    previous = spending[
        spending["transaction_date"].between(previous_month_start, previous_month_cutoff)
    ]["spending"].sum()

    prior_year_start = month_start - pd.DateOffset(years=1)
    prior_year_last = calendar.monthrange(prior_year_start.year, prior_year_start.month)[1]
    prior_year_cutoff = prior_year_start.replace(day=min(days_elapsed, prior_year_last))
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


def comparable_year_months(frame: pd.DataFrame) -> pd.DataFrame:
    spending = spending_frame(frame, personal_only=True)
    if spending.empty:
        return pd.DataFrame(columns=["year", "month_number", "spending"])
    grouped = spending.groupby(["year", "month_number"])["spending"].sum().reset_index()
    return grouped.sort_values(["year", "month_number"])


def academic_period_spending(frame: pd.DataFrame) -> pd.DataFrame:
    spending = spending_frame(frame, personal_only=True)
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
    grouped = (
        spending[spending["month"].isin([current_period, previous_period])]
        .groupby(["category", "month"])["spending"]
        .sum()
        .unstack(fill_value=0)
    )
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


def recurring_transactions(frame: pd.DataFrame) -> pd.DataFrame:
    expenses = spending_frame(frame)
    columns = [
        "merchant",
        "frequency",
        "occurrences",
        "average_amount",
        "median_interval_days",
        "last_seen",
    ]
    if expenses.empty:
        return pd.DataFrame(columns=columns)

    working = expenses[expenses["transaction_type"].eq("expense")].copy()
    merchant = working["merchant"].fillna("").astype(str).str.strip()
    description = working["description"].fillna("").astype(str)
    source = merchant.mask(merchant.eq(""), description)
    working["merchant_key"] = (
        source.str.casefold().str.replace(r"\d+", "", regex=True).str.split().str.join(" ")
    )
    recurring: list[dict[str, object]] = []
    for key, group in working.groupby("merchant_key"):
        group = group.sort_values("transaction_date")
        if not key or len(group) < 3:
            continue
        dates = pd.to_datetime(group["transaction_date"])
        intervals = dates.diff().dt.days.dropna()
        if intervals.empty:
            continue
        median_interval = float(intervals.median())
        mean_amount = float(group["amount"].mean())
        coefficient_of_variation = (
            float(group["amount"].std(ddof=0) / mean_amount) if mean_amount else 1
        )
        if 5 <= median_interval <= 10:
            frequency = "Weekly"
        elif 20 <= median_interval <= 40:
            frequency = "Monthly"
        elif 75 <= median_interval <= 105:
            frequency = "Quarterly"
        else:
            continue
        if coefficient_of_variation > 0.2:
            continue
        recurring.append(
            {
                "merchant": str(key).title(),
                "frequency": frequency,
                "occurrences": len(group),
                "average_amount": mean_amount,
                "median_interval_days": median_interval,
                "last_seen": group["transaction_date"].max().date(),
            }
        )
    return pd.DataFrame(recurring, columns=columns).sort_values("average_amount", ascending=False)


def spending_anomalies(frame: pd.DataFrame) -> pd.DataFrame:
    expenses = spending_frame(frame)
    columns = [
        "transaction_date",
        "description",
        "category",
        "amount",
        "typical_amount",
        "anomaly_score",
    ]
    if expenses.empty:
        return pd.DataFrame(columns=columns)

    anomalies: list[pd.DataFrame] = []
    for _, group in expenses[expenses["transaction_type"].eq("expense")].groupby("category"):
        if len(group) < 4:
            continue
        median = float(group["amount"].median())
        mad = float((group["amount"] - median).abs().median())
        scored = group.copy()
        if mad:
            scored["anomaly_score"] = 0.6745 * (scored["amount"] - median) / mad
        else:
            scored["anomaly_score"] = np.where(
                scored["amount"] > max(median * 1.5, median + 25), 10.0, 0.0
            )
        scored["typical_amount"] = median
        anomalies.append(scored[scored["anomaly_score"] >= 3.5])
    if not anomalies:
        return pd.DataFrame(columns=columns)
    return (
        pd.concat(anomalies, ignore_index=True)[columns]
        .sort_values("anomaly_score", ascending=False)
        .reset_index(drop=True)
    )


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
