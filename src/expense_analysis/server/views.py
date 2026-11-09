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
    transactions_frame,
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
    scope_label: str,
    summary: Row,
    month_comparison: Row,
    year_comparison: Row,
    drivers: pd.DataFrame,
    recurring: pd.DataFrame,
    month_rows: list[Row],
    as_of: date,
    duplicate_groups: int,
) -> list[Row]:
    signals: list[Row] = []
    change = month_comparison["change"]
    if change is not None:
        percent = month_comparison["percent"]
        prior_start = date.fromisoformat(month_comparison["prior_start"])
        prior_end = date.fromisoformat(month_comparison["prior_end"])
        text = (
            f"{scope_label} is {format_dollars(change, signed=True)}"
            + (f" ({percent:+.1f}%)" if percent is not None else "")
            + f" vs {short_date(prior_start)}–{prior_end.day}."
        )
        if change > 0 and not drivers.empty and float(drivers.iloc[0]["change"]) > 0:
            top = drivers.iloc[0]
            increase = format_dollars(to_cents(top["change"]), signed=True)
            text += f" Biggest increase: {top['category']} ({increase})."
        signals.append({"tone": "up" if change > 0 else "ok", "text": text})
    if not recurring.empty:
        horizon = as_of + timedelta(days=14)
        upcoming = recurring[
            recurring["status"].eq("Active")
            & recurring["next_expected"].map(lambda day: as_of < day <= horizon)
        ].sort_values("next_expected")
        for _, item in upcoming.head(2).iterrows():
            signals.append(
                {
                    "tone": "info",
                    "text": f"{item['merchant']} "
                    f"~{format_dollars(to_cents(item['average_amount']))} is expected "
                    f"{short_date(item['next_expected'])} ({item['frequency'].lower()}).",
                }
            )
        stopped = recurring[recurring["status"].eq("Possibly stopped")]
        if not stopped.empty:
            names = ", ".join(str(name) for name in stopped["merchant"].head(3))
            signals.append(
                {"tone": "info", "text": f"Possibly stopped: {names}. Cancelled on purpose?"}
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
    elif month_rows:
        signals.append(
            {
                "tone": "ok",
                "text": f"All {len(month_rows)} entries this month have a category.",
            }
        )
    if summary["review_count"]:
        signals.append(
            {
                "tone": "warn",
                "text": f"{summary['review_count']} purchase(s) use a category you haven't "
                "sorted into everyday, bills or big stuff yet. They count as everyday for now.",
                "action": "treatments",
            }
        )
    if year_comparison["previous"] is not None:
        signals.append(
            {
                "tone": "info",
                "text": f"Same point last year: {format_dollars(year_comparison['previous'])} "
                f"({format_dollars(year_comparison['change'], signed=True)}).",
            }
        )
    if duplicate_groups:
        signals.append(
            {
                "tone": "warn",
                "text": f"{duplicate_groups} group(s) of identical transactions exist. "
                "Check them before deleting anything.",
            }
        )
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
    scope_label = "Everyday" if everyday else "All spending"
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
            if bill["due"].strftime("%Y-%m") == month or bill["status"] in ("late", "soon")
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
    if not frame.empty:
        frame = frame[frame["transaction_date"].dt.date <= as_of]
    scoped_frame = (
        frame[frame["spending_treatment"].eq("Everyday")] if everyday and not frame.empty else frame
    )
    monthly = monthly_spending(scoped_frame)
    drivers = spending_drivers(scoped_frame, as_of) if not scoped_frame.empty else pd.DataFrame()
    recurring = recurring_transactions(frame, as_of) if not frame.empty else pd.DataFrame()

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
            "signals": _signals(
                scope_label=scope_label,
                summary=summary,
                month_comparison=month_comparison,
                year_comparison=year_comparison,
                drivers=drivers,
                recurring=recurring,
                month_rows=month_rows,
                as_of=as_of,
                duplicate_groups=len(database.duplicate_groups()),
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
    if not frame.empty:
        frame = frame[frame["transaction_date"].dt.date <= as_of]
    scoped = (
        frame[frame["spending_treatment"].eq("Everyday")] if everyday and not frame.empty else frame
    )
    drivers = spending_drivers(scoped, as_of) if not scoped.empty else pd.DataFrame()
    recurring = recurring_transactions(frame, as_of) if not frame.empty else pd.DataFrame()
    anomalies = spending_anomalies(scoped) if not scoped.empty else pd.DataFrame()
    cash = cash_flow_by_month(frame)
    terms = period_totals(
        [r for r in classified if not everyday or r["spending_treatment"] == "Everyday"], as_of
    )
    monthly = monthly_spending(scoped)
    savings = savings_summary(frame)

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
    return payload(
        {
            **result,
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
