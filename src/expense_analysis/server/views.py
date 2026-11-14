"""JSON payloads for the web app, built only from the UI-independent core.

Every amount leaves here as integer cents. Pages format money; they never
recompute budgets, comparisons or classifications.
"""

from __future__ import annotations

import csv
import io
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ..analytics import (
    cash_flow_by_month,
    monthly_spending,
    recurring_transactions,
    savings_summary,
    spending_anomalies,
    spending_drivers,
    spending_forecast,
    transactions_frame,
    weekly_spending,
)
from ..categories import keyword_rules, suggestion_data
from ..choices import choice_options, unused_choices
from ..config import DATABASE_PATH, LOCAL_CONFIG_PATH, TRANSACTION_TYPES, AppConfig
from ..database import Database
from ..import_export import ImportPreview, decode_csv, header_key
from ..models import comparable_day, format_dollars, month_after, normalize_text
from ..spending_summary import comparison, previous_year, spending_summary
from ..spending_treatment import CATEGORY_DEFAULT, TREATMENTS, classify_spending
from ..term_budget import (
    CADENCES,
    HOUSING,
    BudgetSettings,
    bill_totals,
    period_for,
    period_kind_lookup,
    period_totals,
    school_periods,
    term_budget,
    weekly_line,
)
from ..university_presets import UCLA_CALENDAR_SOURCE, UCLA_QUARTERS

Row = dict[str, Any]
CHOICE_KINDS = ("category", "account", "payment_method")
USAGE_PREVIEW_LIMIT = 20


def jsonable(value: Any) -> Any:
    """Plain JSON values: ISO dates, Python numbers, and None for NaN."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date().isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating | float):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def payload(value: Row) -> Row:
    result = jsonable(value)
    assert isinstance(result, dict)
    return result


def to_cents(value: Any) -> int:
    number = float(value)
    return 0 if math.isnan(number) else int(round(number * 100))


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def signed_amount(row: Row) -> int:
    return int(row["amount_cents"]) * (-1 if row["transaction_type"] == "refund" else 1)


def serialize_row(row: Row) -> Row:
    keys = (
        "id",
        "description",
        "amount_cents",
        "category",
        "account",
        "payment_method",
        "merchant",
        "transaction_type",
        "notes",
        "created_at",
        "updated_at",
        "spending_treatment",
        "treatment_review",
    )
    data = {key: row[key] for key in keys if key in row}
    data["transaction_date"] = str(row["transaction_date"])[:10]
    return data


def reporting_months(rows: list[Row], today: date) -> list[str]:
    current = today.strftime("%Y-%m")
    options = {current, *(str(r["transaction_date"])[:7] for r in rows)}
    return sorted(month for month in options if month <= current)


def month_bounds(month: str, today: date) -> tuple[date, date, date]:
    first = date.fromisoformat(month + "-01")
    last = month_after(first, 1) - timedelta(days=1)
    return first, min(today, last), last


def _comparison(rows: list[Row], start: date, end: date, prior: date, prior_end: date) -> Row:
    return payload(comparison(rows, start, end, prior, prior_end))


def _in_scope(frame: pd.DataFrame, everyday: bool) -> pd.DataFrame:
    """The Everyday rows of a classified frame, or all of it."""
    if not everyday or frame.empty:
        return frame
    return frame[frame["spending_treatment"].eq("Everyday")]


def _vocabulary(database: Database, config: AppConfig) -> Row:
    rows = database.list_transactions()
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        merchant = str(row["merchant"]).strip()
        if merchant:
            names[normalize_text(merchant)][merchant] += 1
    suggestions = suggestion_data(database, config)
    return {
        "rules": [[keyword, category] for keyword, category in suggestions["rules"]],
        "merchants": suggestions["merchants"],
        "merchant_names": {key: counts.most_common(1)[0][0] for key, counts in names.items()},
    }


def bootstrap(database: Database, config: AppConfig, today: date) -> Row:
    return {
        "today": today.isoformat(),
        "categories": [
            {"name": name, "spending_class": config.spending_class(name)}
            for name in choice_options(database, config, "category")
        ],
        "accounts": choice_options(database, config, "account"),
        "payment_methods": choice_options(database, config, "payment_method"),
        "default_account": config.default_account,
        "default_payment_method": config.default_payment_method,
        "transaction_types": list(TRANSACTION_TYPES),
        "treatments": list(TREATMENTS),
        "transaction_count": database.count_transactions(),
        **_vocabulary(database, config),
    }


def _signals(
    *,
    summary: Row,
    bills: list[Row],
    month_rows: list[Row],
    rows: list[Row],
    duplicates: list[Row],
) -> list[Row]:
    """Banners for things that need doing, most pressing first.

    Comparisons and upcoming charges are not banners: the panel and the Coming up
    card show those. Each banner names where to fix it.
    """
    signals: list[Row] = []
    # A bill without a category can never show a payment, so it is not news.
    late = [bill for bill in bills if bill["status"] == "late" and bill["categories"]]
    if len(late) == 1:
        bill = late[0]
        signals.append(
            {
                "tone": "up",
                "text": f"{bill['name']} ({format_dollars(bill['amount'])}) was due "
                f"{short_date(bill['due'])} and no payment shows up.",
                "action": "bills",
            }
        )
    elif late:
        names = ", ".join(dict.fromkeys(str(bill["name"]) for bill in late))
        signals.append(
            {
                "tone": "up",
                "text": f"{len(late)} bills are past due with no payment showing: {names}.",
                "action": "bills",
            }
        )
    unknown = sum(row["category"] == "Uncategorized" for row in month_rows)
    if unknown:
        signals.append(
            {
                "tone": "warn",
                "text": f"{unknown} entr{'y' if unknown == 1 else 'ies'} this month need"
                f"{'s' if unknown == 1 else ''} a category.",
                "action": "uncategorized",
            }
        )
    review = summary["review_count"]
    if review:
        one = review == 1
        signals.append(
            {
                "tone": "warn",
                "text": f"{review} purchase{'' if one else 's'} this month "
                f"{'is' if one else 'are'} in a category you haven't marked as everyday, "
                f"a bill or big stuff. Until you do, {'it counts' if one else 'they count'} "
                "against the weekly line.",
                "action": "treatments",
            }
        )
    if duplicates:
        count = len(duplicates)
        by_id = {row["id"]: row for row in rows}
        first = by_id.get(str(duplicates[0]["transaction_ids"]).split(",")[0])
        signal: Row = {
            "tone": "warn",
            "text": f"{count} transaction{'' if count == 1 else 's'} "
            f"{'is' if count == 1 else 'are'} saved more than once with the same date, "
            "amount and description.",
        }
        if first is not None:
            day = str(first["transaction_date"])[:10]
            signal["action"] = "duplicates"
            signal["filter"] = {"start": day, "end": day, "q": first["description"]}
        signals.append(signal)
    return signals


def _week_view(week: Row | None) -> Row | None:
    if week is None:
        return None
    return {
        key: week[key]
        for key in (
            "label",
            "start",
            "end",
            "line",
            "spent",
            "left",
            "days_left",
            "per_day",
            "pace",
            "days",
        )
    }


def overview(
    database: Database, config: AppConfig, *, month: str | None, scope: str, today: date
) -> Row:
    rows = database.list_transactions()
    settings = database.get_budget_settings()
    rules = database.get_spending_rules()
    months = reporting_months(rows, today)
    month = month if month in months else today.strftime("%Y-%m")
    first, as_of, last = month_bounds(month, today)
    is_current = (as_of.year, as_of.month) == (today.year, today.month)
    summary = spending_summary(settings, rows, as_of, rules)
    classified = classify_spending(rows, settings, rules)
    term = term_budget(settings, rows, today, rules)
    everyday = scope != "all"
    scoped = [r for r in classified if not everyday or r["spending_treatment"] == "Everyday"]

    def within(row: Row, start: date, end: date) -> bool:
        return start.isoformat() <= str(row["transaction_date"])[:10] <= end.isoformat()

    spending_rows = [
        r
        for r in scoped
        if r["transaction_type"] in ("expense", "refund") and within(r, first, as_of)
    ]
    days = []
    for number in range(1, last.day + 1):
        day = first.replace(day=number)
        hits = [r for r in spending_rows if str(r["transaction_date"])[:10] == day.isoformat()]
        days.append(
            {
                "date": day.isoformat(),
                "spent": sum(signed_amount(r) for r in hits),
                "count": len(hits),
                "future": day > as_of,
            }
        )
    by_category: dict[str, int] = defaultdict(int)
    for row in spending_rows:
        by_category[row["category"]] += signed_amount(row)
    categories = [
        {"category": name, "spent": amount}
        for name, amount in sorted(by_category.items(), key=lambda item: -item[1])
        if amount
    ]
    spent = sum(signed_amount(r) for r in spending_rows)

    prior_month = month_after(first, -1)
    prior_month_end = prior_month.replace(
        day=comparable_day(as_of, prior_month.year, prior_month.month)
    )
    prior_month_last = first - timedelta(days=1)
    week_start = as_of - timedelta(days=as_of.weekday())
    month_comparison = _comparison(scoped, first, as_of, prior_month, prior_month_end)
    week_comparison = _comparison(
        scoped, week_start, as_of, week_start - timedelta(days=7), as_of - timedelta(days=7)
    )
    year_comparison = _comparison(scoped, first, as_of, previous_year(first), previous_year(as_of))
    prior_total = sum(
        signed_amount(r)
        for r in scoped
        if r["transaction_type"] in ("expense", "refund")
        and within(r, prior_month, prior_month_last)
    )
    has_prior = any(within(r, prior_month, prior_month_last) for r in scoped)

    week = _week_view(term["week"]) if is_current else None
    budget = (
        {
            "week": week,
            "period": term["period"]["name"],
            "saved": term["totals"]["saved"],
            "weeks_done": term["totals"]["weeks_done"],
            "source": term["line"]["source"],
        }
        if week
        else None
    )
    bills = (
        [
            bill
            for bill in term["bills"]
            if bill["due"].strftime("%Y-%m") == month or bill["status"] in ("late", "part", "soon")
        ]
        if is_current
        else []
    )

    month_rows = [r for r in classified if within(r, first, as_of)]
    purchases = [r for r in month_rows if r["transaction_type"] in ("expense", "refund")]
    ticker_rows = (
        [r for r in purchases if str(r["transaction_date"])[:10] == as_of.isoformat()]
        if is_current
        else purchases[:8]
    )
    frame = transactions_frame(classified, config)
    timeline = frame
    if not frame.empty:
        timeline = frame[frame["transaction_date"].dt.date <= today]
        frame = frame[frame["transaction_date"].dt.date <= as_of]
    # The month strip is a way to move between months, so it runs through today
    # whichever month is open.
    monthly = monthly_spending(_in_scope(timeline, everyday), through=today)
    weekly = weekly_spending(_in_scope(timeline, everyday), through=today)
    upcoming: list[Row] = []
    if is_current and not frame.empty:
        # Repeating charges due in the next two weeks that no bill already covers.
        recurring = recurring_transactions(frame, as_of)
        covered = settings.bill_categories if settings else {}
        horizon = as_of + timedelta(days=14)
        for _, item in recurring.sort_values("next_expected").iterrows():
            if (
                item["status"] == "Active"
                and as_of < item["next_expected"] <= horizon
                and item["category"] not in covered
            ):
                upcoming.append(
                    {
                        "name": item["merchant"],
                        "amount": to_cents(item["average_amount"]),
                        "due": item["next_expected"],
                        "frequency": item["frequency"],
                    }
                )

    return payload(
        {
            "month": month,
            "months": months,
            "scope": "everyday" if everyday else "all",
            "as_of": as_of,
            "is_current": is_current,
            "days_in_month": last.day,
            "has_transactions": bool(rows),
            "spent": spent,
            "month_spent": summary["month_spent"],
            "treatment_totals": summary["treatment_totals"],
            "review_count": summary["review_count"],
            "budget": budget,
            "baseline": {"total": prior_total, "month": prior_month.strftime("%Y-%m")}
            if has_prior
            else None,
            "comparisons": {
                "month": month_comparison,
                "week": week_comparison,
                "year": year_comparison,
            },
            "days": days,
            "categories": categories,
            "bills": bills,
            "bill_totals": bill_totals(bills),
            "upcoming": upcoming,
            "ticker": {
                "label": "TODAY" if is_current else "LATEST",
                "items": [
                    {
                        "name": (r["merchant"] or r["description"]),
                        "amount": int(r["amount_cents"]),
                        "refund": r["transaction_type"] == "refund",
                    }
                    for r in ticker_rows
                ],
                "total": sum(signed_amount(r) for r in ticker_rows),
            },
            "recent": [serialize_row(r) for r in month_rows[:8]],
            "monthly": [
                {
                    "month": str(item["month"]),
                    "spent": to_cents(item["spending"]),
                    "rolling_3": to_cents(item["rolling_3"]),
                }
                for _, item in monthly.tail(12).iterrows()
            ],
            "weekly": [
                {
                    "week": item["week"],
                    "end": item["week"] + timedelta(days=6),
                    "label": period_for(item["week"]).label(item["week"]),
                    "spent": to_cents(item["spending"]),
                    "rolling_4": to_cents(item["rolling_4"]),
                }
                for _, item in weekly.tail(12).iterrows()
            ],
            "signals": _signals(
                summary=summary,
                bills=term["bills"] if is_current else [],
                month_rows=month_rows,
                rows=rows,
                duplicates=database.duplicate_groups(),
            ),
        }
    )


def insights(
    database: Database, config: AppConfig, *, month: str | None, scope: str, today: date
) -> Row:
    rows = database.list_transactions()
    settings = database.get_budget_settings()
    rules = database.get_spending_rules()
    months = reporting_months(rows, today)
    month = month if month in months else today.strftime("%Y-%m")
    _, as_of, _ = month_bounds(month, today)
    everyday = scope != "all"
    classified = classify_spending(rows, settings, rules)
    frame = transactions_frame(classified, config)
    timeline = frame
    if not frame.empty:
        timeline = frame[frame["transaction_date"].dt.date <= today]
        frame = frame[frame["transaction_date"].dt.date <= as_of]
    scoped = _in_scope(frame, everyday)
    # The trend and the forecast look from today, whichever month is open.
    timeline = _in_scope(timeline, everyday)
    drivers = spending_drivers(scoped, as_of) if not scoped.empty else pd.DataFrame()
    recurring = recurring_transactions(frame, as_of) if not frame.empty else pd.DataFrame()
    anomalies = spending_anomalies(scoped) if not scoped.empty else pd.DataFrame()
    cash = cash_flow_by_month(frame)
    terms = period_totals(
        [r for r in classified if not everyday or r["spending_treatment"] == "Everyday"], as_of
    )
    monthly = monthly_spending(timeline, through=today)
    savings = savings_summary(frame)
    forecast = spending_forecast(timeline, today, kind_of=period_kind_lookup())

    year = term_budget(settings, rows, as_of, rules)["year"]
    return payload(
        {
            "month": month,
            "months": months,
            "scope": "everyday" if everyday else "all",
            "as_of": as_of,
            "has_transactions": bool(rows),
            "drivers": [
                {
                    "category": item["category"],
                    "current": to_cents(item["current"]),
                    "previous": to_cents(item["previous"]),
                    "change": to_cents(item["change"]),
                    "percent": item["percent_change"],
                }
                for _, item in drivers.head(10).iterrows()
            ],
            "recurring": [
                {
                    "merchant": item["merchant"],
                    "frequency": item["frequency"],
                    "occurrences": item["occurrences"],
                    "average": to_cents(item["average_amount"]),
                    "interval_days": item["median_interval_days"],
                    "last_seen": item["last_seen"],
                    "next_expected": item["next_expected"],
                    "status": item["status"],
                }
                for _, item in recurring.iterrows()
            ],
            "anomalies": [
                {
                    "date": item["transaction_date"],
                    "description": item["description"],
                    "category": item["category"],
                    "amount": to_cents(item["amount"]),
                    "typical": to_cents(item["typical_amount"]),
                    "score": item["anomaly_score"],
                }
                for _, item in anomalies.iterrows()
            ],
            "cash_flow": [
                {
                    "month": str(item["month"]),
                    "income": to_cents(item["income"]),
                    "expenses": to_cents(item["expenses"]),
                    "refunds": to_cents(item["refunds"]),
                    "net": to_cents(item["net_cash_flow"]),
                }
                for _, item in cash.iterrows()
            ],
            "terms": terms,
            "monthly": [
                {
                    "month": str(item["month"]),
                    "spent": to_cents(item["spending"]),
                    "rolling_3": to_cents(item["rolling_3"]),
                    "rolling_6": to_cents(item["rolling_6"]),
                    "rolling_12": to_cents(item["rolling_12"]),
                }
                for _, item in monthly.iterrows()
            ],
            "forecast": {
                "level": to_cents(forecast.level),
                "typical_miss": None
                if forecast.typical_miss is None
                else to_cents(forecast.typical_miss),
                "history_months": forecast.history_months,
                "weekly_rates": {
                    kind: to_cents(rate) for kind, rate in forecast.weekly_rates.items()
                },
                "months": [
                    {
                        "month": str(item["month"]),
                        "expected": to_cents(item["expected"]),
                        "low": to_cents(item["low"]),
                        "high": to_cents(item["high"]),
                        "spent": to_cents(item["spent"]),
                        "partial": bool(item["partial"]),
                    }
                    for _, item in forecast.months.iterrows()
                ],
            },
            "savings": {
                "income": to_cents(savings["income"] or 0),
                "net_outflow": to_cents(savings["net_outflow"] or 0),
                "savings": to_cents(savings["savings"] or 0),
                "rate": savings["savings_rate"],
            },
            "year": year,
            "duplicate_groups": len(database.duplicate_groups()),
        }
    )


def treatment_table(
    config: AppConfig, rows: list[Row], settings: BudgetSettings | None, rules: Row
) -> list[Row]:
    saved_rules = rules.get("categories", {})
    bills = settings.bill_categories if settings else {}
    categories = sorted(
        set(config.categories) | {r["category"] for r in rows} | set(saved_rules) | set(bills)
    )
    table = []
    for category in categories:
        saved = saved_rules.get(category, "Commitments" if category in bills else None)
        suggested = (
            "Commitments"
            if category in config.fixed_categories
            else "Irregular"
            if category.casefold() in ("flights", "flight", "airfare", "travel")
            else "Everyday"
        )
        table.append({"category": category, "treatment": saved or suggested, "saved": bool(saved)})
    return table


def budget(database: Database, config: AppConfig, *, today: date, period: str | None) -> Row:
    settings = database.get_budget_settings()
    rows = database.list_transactions()
    rules = database.get_spending_rules()
    day = date.fromisoformat(period) if period else None
    result = term_budget(settings, rows, today, rules, day=day)
    week = result["week"]
    everyday = [
        r for r in classify_spending(rows, settings, rules) if r["spending_treatment"] == "Everyday"
    ]
    return payload(
        {
            **result,
            # This week against the same weekdays of last week, as the overview shows it.
            "comparison": _comparison(
                everyday,
                week["start"],
                today,
                week["start"] - timedelta(days=7),
                today - timedelta(days=7),
            )
            if week
            else None,
            "big_stuff": [serialize_row(row) for row in result["big_stuff"][:30]],
            "saved_settings": settings is not None,
            "housing_options": list(HOUSING),
            "housing_estimates": {
                housing: {
                    key: weekly_line(BudgetSettings(housing=housing))[key]
                    for key in ("school_weekly", "school_yearly")
                }
                for housing in HOUSING
            },
            "cadences": list(CADENCES),
            "periods": [
                {"name": p.name, "kind": p.kind, "start": p.start, "end": p.end}
                for p in school_periods()
                if p.start <= today
            ],
            "treatments": treatment_table(config, rows, settings, rules),
            "treatment_options": list(TREATMENTS),
            "category_default": CATEGORY_DEFAULT,
        }
    )


def choices(database: Database, config: AppConfig) -> Row:
    result: Row = {}
    for kind in CHOICE_KINDS:
        counts = database.choice_counts(kind)
        unused = set(unused_choices(database, config, kind))
        entries = []
        for name in choice_options(database, config, kind):
            entry: Row = {"name": name, "count": counts.get(name, 0), "unused": name in unused}
            if kind == "category":
                entry["spending_class"] = config.spending_class(name)
                entry["locked"] = name == "Uncategorized"
            else:
                entry["default"] = name == (
                    config.default_account if kind == "account" else config.default_payment_method
                )
            entries.append(entry)
        result[kind] = entries
    result["keyword_rules"] = keyword_rules(database, config)
    return result


def choice_usage(database: Database, config: AppConfig, kind: str, name: str) -> Row:
    if kind not in CHOICE_KINDS:
        raise ValueError("This field uses fixed choices")
    count = database.choice_counts(kind).get(name, 0)
    return payload(
        {
            "kind": kind,
            "name": name,
            "count": count,
            "unused": name in unused_choices(database, config, kind),
            "latest": [
                serialize_row(row)
                for row in database.latest_with_choice(kind, name, USAGE_PREVIEW_LIMIT)
            ],
            "replacements": [
                value
                for value in choice_options(database, config, kind)
                if value != name and not (kind == "category" and value == "Uncategorized")
            ],
        }
    )


def unknown_import_categories(content: bytes, config: AppConfig) -> list[str]:
    labels = sorted(
        {
            str(value).strip()
            for row in csv.DictReader(io.StringIO(decode_csv(content)))
            for key, value in row.items()
            if isinstance(key, str) and header_key(key) == "category" and value
        }
    )
    aliases = dict(config.category_aliases)
    return [label for label in labels if label not in config.categories and label not in aliases]


def import_preview(preview: ImportPreview, unknown: list[str], config: AppConfig) -> Row:
    rows = []
    for row in preview.rows:
        draft = row.draft
        rows.append(
            {
                "row": row.row_number,
                "status": "invalid" if row.errors else "duplicate" if row.duplicate else "ready",
                "date": draft.transaction_date if draft else None,
                "description": draft.description if draft else "",
                "amount_cents": draft.amount_cents if draft else None,
                "category": draft.category if draft else "",
                "type": draft.transaction_type if draft else "",
                "merchant": draft.merchant if draft else "",
                "issue": "; ".join(row.errors),
            }
        )
    return payload(
        {
            "rows": rows,
            "ready": len(preview.valid_drafts),
            "duplicates": preview.duplicate_count,
            "invalid": preview.invalid_count,
            "unknown_categories": unknown,
            "category_options": list(config.categories),
        }
    )


def settings(database: Database, config: AppConfig) -> Row:
    return payload(
        {
            "database_path": str(DATABASE_PATH),
            "config_path": str(LOCAL_CONFIG_PATH),
            "config_exists": LOCAL_CONFIG_PATH.exists(),
            "transaction_count": database.count_transactions(),
            "binding": "127.0.0.1",
            "school_calendar": {
                "source": UCLA_CALENDAR_SOURCE,
                "quarters": [dict(q) for q in UCLA_QUARTERS],
            },
        }
    )
