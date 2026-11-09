"""Weekly budgeting on the real school calendar.

The budget is a weekly *line*: UCLA's own everyday living estimate (food,
transportation, personal) spread over the weeks of the school year, or a weekly
amount the student picks. Every Monday starts fresh at the line. Money left at
the end of a week is counted as saved; it never raises the next week's line.

Weeks follow the registrar's quarters: Week 0 when instruction starts mid-week,
Weeks 1-10, then finals week. The gaps between quarters are breaks, and the
weeks after spring finals are summer. Bills (rent, phone, tuition) and big
one-off purchases are tracked beside the line, never inside it.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from .spending_treatment import classify_spending
from .university_presets import (
    UCLA_2026,
    UCLA_QUARTERS,
    UCLA_SUMMER_ENDS,
    QuarterDates,
    everyday_estimate,
)

CADENCES = ("Monthly", "Each quarter", "Once")
HOUSING = tuple(UCLA_2026["housing"])
PAID_WINDOW = timedelta(days=30)


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def net(row: dict[str, Any]) -> int:
    return int(row["amount_cents"]) * (-1 if row["transaction_type"] == "refund" else 1)


def _day(row: dict[str, Any]) -> str:
    return str(row["transaction_date"])[:10]


@dataclass(frozen=True)
class Bill:
    name: str
    amount_cents: int
    categories: tuple[str, ...]
    cadence: str = "Monthly"
    due_day: int = 1
    due: date | None = None


@dataclass(frozen=True)
class BudgetSettings:
    housing: str = "Off-campus"
    # None follows the school's estimate; a number is the student's own line.
    weekly_cents: int | None = None
    bills: tuple[Bill, ...] = field(default_factory=tuple)

    def validate(self) -> BudgetSettings:
        if self.housing not in HOUSING:
            raise ValueError("Choose on-campus, off-campus or commuter.")
        if self.weekly_cents is not None and (
            type(self.weekly_cents) is not int or self.weekly_cents <= 0
        ):
            raise ValueError("Your weekly amount must be more than $0.")
        names: set[str] = set()
        categories: set[str] = set()
        for bill in self.bills:
            if not bill.name.strip() or bill.name in names:
                raise ValueError("Give every bill a unique name.")
            names.add(bill.name)
            if type(bill.amount_cents) is not int or bill.amount_cents < 0:
                raise ValueError(f"{bill.name}: enter an amount of $0 or more.")
            if bill.cadence not in CADENCES:
                raise ValueError(f"{bill.name}: choose monthly, each quarter or once.")
            if type(bill.due_day) is not int or not 1 <= bill.due_day <= 31:
                raise ValueError(f"{bill.name}: the due day must be between 1 and 31.")
            if bill.cadence == "Once" and bill.due is None:
                raise ValueError(f"{bill.name}: choose the date it is due.")
            for category in bill.categories:
                if not category.strip():
                    raise ValueError("Category names cannot be empty.")
                if category in categories:
                    raise ValueError(f"{category} is used by two bills. Map it to one.")
                categories.add(category)
        return self

    @property
    def bill_categories(self) -> dict[str, str]:
        return {category: bill.name for bill in self.bills for category in bill.categories}

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": 3,
            "housing": self.housing,
            "weekly_cents": self.weekly_cents,
            "bills": [
                {
                    "name": bill.name,
                    "amount_cents": bill.amount_cents,
                    "categories": list(bill.categories),
                    "cadence": bill.cadence,
                    "due_day": bill.due_day,
                    "due": bill.due.isoformat() if bill.due else None,
                }
                for bill in self.bills
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BudgetSettings:
        version = payload.get("schema_version")
        if version in (1, 2):
            return _from_legacy_plan(payload)
        if version != 3:
            raise ValueError("Unsupported budget version.")
        return cls(
            housing=payload.get("housing", "Off-campus"),
            weekly_cents=payload.get("weekly_cents"),
            bills=tuple(
                Bill(
                    name=item["name"],
                    amount_cents=item["amount_cents"],
                    categories=tuple(item.get("categories", ())),
                    cadence=item.get("cadence", "Monthly"),
                    due_day=item.get("due_day", 1),
                    due=date.fromisoformat(item["due"]) if item.get("due") else None,
                )
                for item in payload.get("bills", ())
            ),
        ).validate()

    def rename_category(self, source: str, name: str) -> BudgetSettings:
        return replace(
            self,
            bills=tuple(
                replace(
                    bill,
                    categories=tuple(
                        dict.fromkeys(
                            name if value == source else value for value in bill.categories
                        )
                    ),
                )
                for bill in self.bills
            ),
        ).validate()


def _from_legacy_plan(payload: dict[str, Any]) -> BudgetSettings:
    """Keep the bills from a month-based plan saved before term budgets."""
    housing = payload.get("reference", {}).get("housing")
    start = date.fromisoformat(payload["start"])
    bills = []
    taken: set[str] = set()
    for item in payload.get("commitments", ()):
        if item.get("treatment", "Commitments") != "Commitments":
            continue
        cadence = {"Monthly": "Monthly", "Quarterly": "Each quarter"}.get(item["cadence"], "Once")
        first = start.year * 12 + start.month - 1 + item.get("first_month", 0)
        categories = tuple(c for c in item["categories"] if c not in taken)
        taken.update(categories)
        bills.append(
            Bill(
                name=item["name"],
                amount_cents=item["amount_cents"],
                categories=categories,
                cadence=cadence,
                due=date(first // 12, first % 12 + 1, 1) if cadence == "Once" else None,
            )
        )
    return BudgetSettings(
        housing=housing if housing in HOUSING else "Off-campus", bills=tuple(bills)
    ).validate()


# ── Calendar ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Period:
    name: str
    kind: str  # quarter | break | summer | month
    start: date  # a Monday
    end: date  # a Sunday
    week_one: date | None = None
    finals: date | None = None
    quarter_begins: date | None = None

    @property
    def weeks(self) -> list[date]:
        return [
            self.start + timedelta(days=7 * i)
            for i in range(((self.end - self.start).days + 1) // 7)
        ]

    def label(self, week: date) -> str:
        if self.kind == "quarter":
            assert self.week_one is not None and self.finals is not None
            if week >= monday(self.finals):
                return "Finals week"
            if week < self.week_one:
                return "Week 0"
            return f"Week {(week - self.week_one).days // 7 + 1}"
        number = self.weeks.index(week) + 1
        if self.kind == "month":
            return f"Week of {week:%b} {week.day}"
        return f"Week {number} of {len(self.weeks)}"


def _quarter_period(quarter: QuarterDates) -> Period:
    instruction = date.fromisoformat(quarter["instruction_begins"])
    ends = date.fromisoformat(quarter["quarter_ends"])
    season = quarter["name"].split()[0]
    return Period(
        name=f"{season} quarter {quarter['name'].split()[1]}",
        kind="quarter",
        start=monday(instruction),
        end=ends + timedelta(days=6 - ends.weekday()),
        week_one=instruction if instruction.weekday() == 0 else monday(instruction) + timedelta(7),
        finals=date.fromisoformat(quarter["finals_begin"]),
        quarter_begins=date.fromisoformat(quarter["quarter_begins"]),
    )


def school_periods() -> list[Period]:
    """Every week from the first known fall to the last known summer, without gaps."""
    quarters = [_quarter_period(q) for q in UCLA_QUARTERS]
    result: list[Period] = []
    for index, quarter in enumerate(quarters):
        result.append(quarter)
        after = quarter.end + timedelta(days=1)
        if index + 1 < len(quarters):
            following = quarters[index + 1]
            if following.start > after:
                season = quarter.name.split()[0]
                kind = "summer" if season == "Spring" else "break"
                name = {
                    "Fall": f"Winter break {quarter.end.year}",
                    "Winter": f"Spring break {following.start.year}",
                    "Spring": f"Summer {after.year}",
                }[season]
                result.append(Period(name, kind, after, following.start - timedelta(days=1)))
        elif quarter.name.startswith("Spring") and str(after.year) in UCLA_SUMMER_ENDS:
            ends = date.fromisoformat(UCLA_SUMMER_ENDS[str(after.year)])
            result.append(Period(f"Summer {after.year}", "summer", after, ends))
    return result


def period_for(day: date) -> Period:
    for period in school_periods():
        if period.start <= day <= period.end:
            return period
    # Outside the published calendar: plain weeks touching this calendar month.
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return Period(f"{day:%B %Y}", "month", monday(first), monday(last) + timedelta(days=6))


def school_year_for(day: date) -> tuple[date, date] | None:
    """Fall week 0 to the end of spring finals for the school year holding ``day``."""
    periods = [p for p in school_periods() if p.kind == "quarter"]
    for index, period in enumerate(periods):
        if period.name.startswith("Fall") and index + 2 < len(periods):
            start, end = period.start, periods[index + 2].end
            summer_end = next(
                (
                    p.end
                    for p in school_periods()
                    if p.kind == "summer" and p.start == end + timedelta(days=1)
                ),
                end,
            )
            if start <= day <= summer_end:
                return start, end
    return None


def school_weeks() -> int:
    """Weeks in the preset's school year (fall week 0 through spring finals)."""
    year = UCLA_2026["academic_year"][:4]
    fall = next(p for p in school_periods() if p.name == f"Fall quarter {year}")
    span = school_year_for(fall.start)
    assert span is not None
    return ((span[1] - span[0]).days + 1) // 7


# ── Budget ────────────────────────────────────────────────────────────────


def weekly_line(settings: BudgetSettings) -> dict[str, Any]:
    components = everyday_estimate(settings.housing)
    yearly = sum(components[name] for name in components if name != "Books")
    weeks = school_weeks()
    school = round(yearly / weeks)
    return {
        "weekly": settings.weekly_cents or school,
        "source": "own" if settings.weekly_cents else "school",
        "school_weekly": school,
        "school_yearly": yearly,
        "school_weeks": weeks,
        "housing": settings.housing,
        "components": components,
        "books_per_quarter": round(components["Books"] / 3),
        "school": UCLA_2026["school"],
        "year": UCLA_2026["academic_year"],
        "source_url": UCLA_2026["source"],
        "verified_on": UCLA_2026["verified_on"],
    }


def _bill_dues(bill: Bill, period: Period) -> list[date]:
    if bill.cadence == "Once":
        return [bill.due] if bill.due and period.start <= bill.due <= period.end else []
    if bill.cadence == "Each quarter":
        return [period.quarter_begins] if period.quarter_begins else []
    dues = []
    month = period.start.replace(day=1)
    while month <= period.end:
        last = calendar.monthrange(month.year, month.month)[1]
        due = month.replace(day=min(bill.due_day, last))
        if period.start <= due <= period.end:
            dues.append(due)
        month = (month + timedelta(days=32)).replace(day=1)
    return dues


def _bills(
    settings: BudgetSettings, spending: list[dict[str, Any]], period: Period, as_of: date
) -> list[dict[str, Any]]:
    result = []
    for bill in settings.bills:
        for due in _bill_dues(bill, period):
            if bill.cadence == "Monthly":
                start = due.replace(day=1)
                end = due.replace(day=calendar.monthrange(due.year, due.month)[1])
            else:
                start, end = due - PAID_WINDOW, due + PAID_WINDOW
            paid = sum(
                net(row)
                for row in spending
                if row["category"] in bill.categories
                and start.isoformat() <= _day(row) <= min(end, as_of).isoformat()
            )
            if paid > 0 and paid >= bill.amount_cents:
                status = "paid"
            elif due < as_of:
                status = "late"
            elif due <= as_of + timedelta(days=7):
                status = "soon"
            else:
                status = "upcoming"
            result.append(
                {
                    "name": bill.name,
                    "amount": bill.amount_cents,
                    "due": due,
                    "paid": paid,
                    "status": status,
                    "categories": list(bill.categories),
                    "cadence": bill.cadence,
                }
            )
    return sorted(result, key=lambda item: item["due"])


def term_budget(
    settings: BudgetSettings | None,
    rows: list[dict[str, Any]],
    as_of: date,
    rules: dict | None = None,
    day: date | None = None,
) -> dict[str, Any]:
    """The weekly picture for the period holding ``day`` (default: today)."""
    settings = settings or BudgetSettings()
    line = weekly_line(settings)
    weekly = line["weekly"]
    period = period_for(day or as_of)
    classified = classify_spending(rows, settings, rules)
    spending = [
        r
        for r in classified
        if r["transaction_type"] in ("expense", "refund") and _day(r) <= as_of.isoformat()
    ]
    everyday = [r for r in spending if r["spending_treatment"] == "Everyday"]
    by_day: dict[str, int] = {}
    for row in everyday:
        by_day[_day(row)] = by_day.get(_day(row), 0) + net(row)

    def spent_between(start: date, end: date) -> int:
        return sum(
            amount
            for key, amount in by_day.items()
            if start.isoformat() <= key <= min(end, as_of).isoformat()
        )

    weeks = []
    current: dict[str, Any] | None = None
    for start in period.weeks:
        end = start + timedelta(days=6)
        state = "past" if end < as_of else "current" if start <= as_of else "future"
        spent = spent_between(start, end) if state != "future" else 0
        week = {
            "start": start,
            "end": end,
            "label": period.label(start),
            "state": state,
            "line": weekly,
            "spent": spent,
            "left": weekly - spent,
            "saved": weekly - spent if state == "past" else None,
        }
        weeks.append(week)
        if state == "current":
            days_left = (end - as_of).days + 1
            elapsed = 7 - days_left + 1
            current = {
                **week,
                "days_left": days_left,
                "per_day": max(0, weekly - spent) // days_left,
                "pace": round(weekly * elapsed / 7),
                "days": [
                    {
                        "date": start + timedelta(days=i),
                        "spent": by_day.get((start + timedelta(days=i)).isoformat(), 0),
                        "future": start + timedelta(days=i) > as_of,
                    }
                    for i in range(7)
                ],
            }

    def total(kind: str) -> int:
        return sum(
            net(r)
            for r in spending
            if r["spending_treatment"] == kind
            and period.start.isoformat() <= _day(r) <= period.end.isoformat()
        )

    big_stuff = [
        r
        for r in spending
        if r["spending_treatment"] == "Irregular"
        and period.start.isoformat() <= _day(r) <= period.end.isoformat()
    ]
    periods = school_periods()
    names = [p.name for p in periods]
    index = names.index(period.name) if period.name in names else None
    year: dict[str, Any] | None = None
    span = school_year_for(as_of)
    if span is not None:
        start, end = span
        days = (end - start).days + 1
        elapsed = min(max((as_of - start).days + 1, 0), days)
        completed = [
            w for w in _weeks_between(start, min(end, as_of)) if w + timedelta(days=6) < as_of
        ]
        year = {
            "start": start,
            "end": end,
            "label": f"{start.year}–{str(start.year + 1)[2:]}",
            "spent": spent_between(start, end),
            "estimate": line["school_yearly"],
            "estimate_to_date": round(line["school_yearly"] * elapsed / days),
            "line_to_date": weekly * len(completed),
            "saved": sum(weekly - spent_between(w, w + timedelta(days=6)) for w in completed),
            "weeks_done": len(completed),
            "weeks": days // 7,
        }
    return {
        "as_of": as_of,
        "line": line,
        "settings": settings.to_dict(),
        "period": {
            "name": period.name,
            "kind": period.kind,
            "start": period.start,
            "end": period.end,
            "is_current": period.start <= as_of <= period.end,
            "first_day": period.quarter_begins,
            "finals": period.finals,
            "previous": periods[index - 1].start if index else None,
            "next": periods[index + 1].start
            if index is not None and index + 1 < len(periods)
            else None,
        },
        "weeks": weeks,
        "week": current,
        "totals": {
            "everyday": total("Everyday"),
            "bills": total("Commitments"),
            "big_stuff": total("Irregular"),
            "saved": sum(w["saved"] for w in weeks if w["saved"] is not None),
            "line_to_date": weekly * sum(w["state"] == "past" for w in weeks),
            "weeks_done": sum(w["state"] == "past" for w in weeks),
        },
        "bills": _bills(settings, spending, period, as_of),
        "big_stuff": sorted(big_stuff, key=_day, reverse=True),
        "year": year,
    }


def _weeks_between(start: date, end: date) -> list[date]:
    first = monday(start)
    return [first + timedelta(days=7 * i) for i in range(((end - first).days // 7) + 1)]


def period_totals(rows: list[dict[str, Any]], as_of: date) -> list[dict[str, Any]]:
    """Net spending per quarter, break and summer that has any activity."""
    result = []
    for period in school_periods():
        if period.start > as_of:
            break
        hits = [
            r
            for r in rows
            if r["transaction_type"] in ("expense", "refund")
            and period.start.isoformat() <= _day(r) <= min(period.end, as_of).isoformat()
        ]
        if hits:
            result.append(
                {
                    "period": period.name,
                    "kind": period.kind,
                    "start": period.start,
                    "spent": sum(net(r) for r in hits),
                    "weeks": len(period.weeks),
                }
            )
    return result
