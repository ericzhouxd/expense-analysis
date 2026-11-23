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
    LARGEST_DAYS,
    cash_flow_by_month,
    frequent_entries,
    largest_purchases,
    monthly_spending,
    savings_summary,
    spending_drivers,
    spending_forecast,
    transactions_frame,
    weekly_spending,
)
from ..autopilot import AutoBudget
from ..categories import keyword_rules
from ..choices import choice_options, entry_defaults, unused_choices
from ..coa_outlook import coa_outlook
from ..config import DATABASE_PATH, LOCAL_CONFIG_PATH, TRANSACTION_TYPES, AppConfig
from ..database import Database
from ..import_export import ImportPreview, decode_csv, header_key
from ..models import (
    comparable_day,
    format_dollars,
    month_after,
    normalize_text,
)
from ..patterns import coa_part
from ..replay import SmartBudget, smart_budget
from ..spending_summary import comparison, previous_year, spending_summary
from ..spending_treatment import CATEGORY_DEFAULT, TREATMENTS, classify_spending
from ..term_budget import (
    CADENCES,
    HOUSING,
    Bill,
    BudgetSettings,
    next_due,
    period_for,
    period_kind_lookup,
    period_totals,
    school_periods,
    term_budget,
)
from ..university_presets import (
    COA_PARTS,
    UCLA_2026,
    UCLA_CALENDAR_SOURCE,
    UCLA_QUARTERS,
)

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


def whole_dollars(cents: int) -> str:
    """For estimates, where cents would claim too much."""
    return f"${round(cents / 100):,}"


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def learned_budget(
    database: Database, config: AppConfig, rows: list[Row], today: date
) -> SmartBudget:
    """The budget the ledger itself describes, with the student's own choices on top."""
    return smart_budget(
        database.get_budget_settings(),
        database.get_spending_rules(),
        rows,
        today,
        config.fixed_categories,
    )


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


def _vocabulary(database: Database) -> Row:
    rows = database.list_transactions()
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        merchant = str(row["merchant"]).strip()
        if merchant:
            names[normalize_text(merchant)][merchant] += 1
    return {
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
        "defaults": entry_defaults(config),
        "transaction_types": list(TRANSACTION_TYPES),
        "treatments": list(TREATMENTS),
        "transaction_count": database.count_transactions(),
        "frequent": [
            payload(item) for item in frequent_entries(database.list_transactions(), today)
        ],
        **_vocabulary(database),
    }


def _signals(
    *,
    bills: list[Row],
    coa: Row | None,
    month_rows: list[Row],
    rows: list[Row],
    duplicates: list[Row],
) -> list[Row]:
    """Banners for things that need doing, most pressing first.

    Comparisons are not banners: the panel shows those. Each shows a short label and
    value and links to where it is fixed; ``text`` says it in full for screen readers.
    """
    signals: list[Row] = []
    # A bill without a category can never show a payment, so it is not news.
    missing = [bill for bill in bills if bill["status"] == "late" and bill["categories"]]
    late = [bill for bill in missing if not bill["learned"]]
    expected = [bill for bill in missing if bill["learned"]]
    if len(late) == 1:
        bill = late[0]
        signals.append(
            {
                "tone": "up",
                "label": "No payment",
                "value": f"{bill['name']} · {short_date(bill['due'])}",
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
                "label": "No payment",
                "value": names,
                "text": f"{len(late)} bills are past due with no payment showing: {names}.",
                "action": "bills",
            }
        )
    if expected:
        names = ", ".join(dict.fromkeys(str(bill["name"]) for bill in expected))
        dues = " and ".join(dict.fromkeys(short_date(bill["due"]) for bill in expected))
        signals.append(
            {
                "tone": "warn",
                "label": "Not seen yet",
                "value": f"{names} · {dues}",
                "text": f"Going by earlier payments, {names} was expected around {dues}. "
                "Nothing like it is recorded yet.",
                "action": "bills",
            }
        )
    if coa and coa["ready"] and coa["verdict"] != "under" and not coa["complete"]:
        over = coa["verdict"] == "over"
        weekly = coa["weekly"]
        signals.append(
            {
                "tone": "up" if over else "warn",
                "label": "Cost of attendance",
                "value": f"{whole_dollars(abs(coa['margin']))} "
                f"{'under' if coa['margin'] >= 0 else 'over'}",
                "text": (
                    f"Everything together is heading for about {whole_dollars(abs(coa['margin']))} "
                    f"{'under' if coa['margin'] >= 0 else 'over'} {coa['school']}'s cost of "
                    f"attendance{'' if over else ', too close to call'}. "
                    + (
                        f"About {whole_dollars(weekly['safe'])} a week of everyday spending "
                        "keeps it there."
                        if weekly["possible"]
                        else "Costs outside everyday spending already pass that."
                    )
                ),
                "action": "coa",
            }
        )
    unknown = sum(row["category"] == "Uncategorized" for row in month_rows)
    if unknown:
        signals.append(
            {
                "tone": "warn",
                "label": "No category",
                "value": str(unknown),
                "text": f"{unknown} entr{'y' if unknown == 1 else 'ies'} this month need"
                f"{'s' if unknown == 1 else ''} a category.",
                "action": "uncategorized",
            }
        )
    if duplicates:
        count = len(duplicates)
        by_id = {row["id"]: row for row in rows}
        first = by_id.get(str(duplicates[0]["transaction_ids"]).split(",")[0])
        signal: Row = {
            "tone": "warn",
            "label": "Duplicates",
            "value": str(count),
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
    smart = learned_budget(database, config, rows, today)
    settings, rules = smart.auto.settings, smart.auto.rules
    months = reporting_months(rows, today)
    month = month if month in months else today.strftime("%Y-%m")
    first, as_of, last = month_bounds(month, today)
    is_current = (as_of.year, as_of.month) == (today.year, today.month)
    summary = spending_summary(settings, rows, as_of, rules)
    classified = classify_spending(rows, settings, rules)
    term = term_budget(settings, rows, today, rules, lines=smart.lines)
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
            # What each finished week of the term came to against its line.
            "weeks": [w["saved"] for w in term["weeks"] if w["saved"] is not None],
            "source": term["line"]["source"],
        }
        if week
        else None
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
            "recent": [serialize_row(r) for r in month_rows[:6]],
            # A finished month shows its own; the one in progress looks back further,
            # so the list isn't empty on the 1st.
            "largest": [
                serialize_row(r)
                for r in largest_purchases(
                    classified,
                    as_of - timedelta(days=LARGEST_DAYS - 1) if is_current else first,
                    as_of,
                )
            ],
            "largest_days": LARGEST_DAYS if is_current else None,
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
                bills=term["bills"] if is_current else [],
                coa=coa_outlook(settings, rows, today, rules, smart.auto.habits)
                if is_current
                else None,
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
    smart = learned_budget(database, config, rows, today)
    settings, rules = smart.auto.settings, smart.auto.rules
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
    cash = cash_flow_by_month(frame)
    terms = period_totals(
        [r for r in classified if not everyday or r["spending_treatment"] == "Everyday"], as_of
    )
    monthly = monthly_spending(timeline, through=today)
    savings = savings_summary(frame)
    forecast = spending_forecast(timeline, today, kind_of=period_kind_lookup())

    year = term_budget(settings, rows, as_of, rules, lines=smart.lines)["year"]
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


def treatment_table(auto: AutoBudget, rules: Row) -> list[Row]:
    """How every category in use counts, whether the student decided it, and why if not."""
    parts = rules.get("parts", {})
    return [
        {
            "category": category,
            "treatment": answer.treatment,
            "pinned": answer.pinned,
            "why": answer.why,
            "part": coa_part(category, parts),
            "part_pinned": category in parts,
        }
        for category, answer in sorted(auto.categories.items())
    ]


def _bill_out(bill: Bill, rows: list[Row], today: date) -> Row:
    return {
        "key": bill.key,
        "name": bill.name,
        "amount_cents": bill.amount_cents,
        "categories": list(bill.categories),
        "cadence": bill.cadence,
        "due_day": bill.due_day,
        "due": bill.due,
        "pinned": bill.pinned,
        "match": sorted(bill.match),
        # A yearly charge is kept as its next date.
        "yearly": bill.key.startswith("Yearly|"),
        "why": bill.why,
        "next_due": next_due(bill, rows, today),
    }


def _automatic(
    smart: SmartBudget, saved: BudgetSettings | None, rows: list[Row], today: date
) -> Row:
    """What was worked out, where each answer came from and what can be changed."""
    auto = smart.auto
    options: dict[str, list[Row]] = {
        "housing": [{"value": name, "text": name} for name in HOUSING],
        "cohort": [{"value": name, "text": name} for name in UCLA_2026["cohorts"]],
        "residency": [
            {"value": True, "text": "Nonresident"},
            {"value": False, "text": "California resident"},
        ],
        "insurance": [
            {"value": True, "text": "UC SHIP"},
            {"value": False, "text": "Waived UC SHIP"},
        ],
    }
    return {
        "facts": [
            {
                "key": fact.key,
                "label": fact.label,
                "value": fact.value,
                "text": fact.text,
                "source": fact.source,
                "why": fact.why,
                "auto_text": fact.auto_text,
                "auto_why": fact.auto_why,
                "options": options[fact.key],
            }
            for fact in auto.facts
        ],
        "bills": [_bill_out(bill, rows, today) for bill in auto.settings.bills],
        "dismissed": [_bill_out(bill, rows, today) for bill in auto.dismissed],
        "dismissed_keys": list(saved.dismissed) if saved else [],
        "weekly_cents": auto.settings.weekly_cents,
        "total_cents": saved.coa.total_cents if saved and saved.coa else None,
        "big_cents": auto.big_cents,
        "record": smart.record,
    }


def budget(database: Database, config: AppConfig, *, today: date, period: str | None) -> Row:
    saved = database.get_budget_settings()
    rows = database.list_transactions()
    smart = learned_budget(database, config, rows, today)
    settings, rules = smart.auto.settings, smart.auto.rules
    day = date.fromisoformat(period) if period else None
    result = term_budget(settings, rows, today, rules, day=day, lines=smart.lines)
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
            "auto": _automatic(smart, saved, rows, today),
            "coa": coa_outlook(settings, rows, today, rules, smart.auto.habits),
            "coa_parts": list(COA_PARTS),
            "cadences": list(CADENCES),
            "periods": [
                {"name": p.name, "kind": p.kind, "start": p.start, "end": p.end}
                for p in school_periods()
                if p.start <= today
            ],
            "treatments": treatment_table(smart.auto, rules),
            "treatment_options": list(TREATMENTS),
            "category_default": CATEGORY_DEFAULT,
        }
    )


def choices(database: Database, config: AppConfig) -> Row:
    defaults = entry_defaults(config)
    result: Row = {"defaults": defaults, "transaction_types": list(TRANSACTION_TYPES)}
    for kind in CHOICE_KINDS:
        counts = database.choice_counts(kind)
        unused = set(unused_choices(database, config, kind))
        entries = []
        for name in choice_options(database, config, kind):
            entry: Row = {"name": name, "count": counts.get(name, 0), "unused": name in unused}
            if kind == "category":
                entry["spending_class"] = config.spending_class(name)
                entry["locked"] = name == "Uncategorized"
            entry["default"] = name == defaults[kind]
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
