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
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import cache
from typing import Any

from .models import name_tokens, same_name
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
# How early a charge for the coming school year may be paid.
EARLY_WINDOW = timedelta(days=60)
# A month belongs to the school year once this many of its days do.
MONTH_SHARE_DAYS = 10
# Payments reaching this share of a bill's amount settle it. What the ledger
# suggests is only a guess, so there less is enough.
PAID_SHARE, LEARNED_SHARE = 0.9, 0.5


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
    # The student's own entry, which what the ledger suggests never replaces.
    pinned: bool = False
    # Only purchases named like this count; empty means the whole category.
    match: frozenset[str] = frozenset()
    # The rest is worked out from the ledger and never saved.
    key: str = ""
    why: str = ""
    # Known due dates, for charges that keep their own calendar.
    dates: tuple[date, ...] = ()
    # No due dates before this one: the lease had not started.
    since: date | None = None
    # Days after a guessed due date before a payment counts as missing.
    grace: int = 0

    def pays(self, row: dict[str, Any]) -> bool:
        """Whether a purchase is a payment toward this bill."""
        return row["category"] in self.categories and (
            not self.match or same_name(self.match, name_tokens(str(row.get("description", ""))))
        )


@dataclass(frozen=True)
class CoaProfile:
    """What decides a student's cost of attendance, besides where they live.

    ``None`` means unknown until the ledger shows it.
    """

    cohort: str | None = None
    nonresident: bool | None = None
    insurance: bool | None = None
    # The student's own total from MyUCLA, when it differs from the published one.
    total_cents: int | None = None

    @property
    def complete(self) -> bool:
        return self.cohort is not None and self.nonresident is not None

    def validate(self) -> CoaProfile:
        if self.cohort is not None and self.cohort not in UCLA_2026["cohorts"]:
            raise ValueError("Choose the year you entered UC.")
        for value in (self.nonresident, self.insurance):
            if value is not None and type(value) is not bool:
                raise ValueError("Choose your residency and health insurance.")
        if self.total_cents is not None and (
            type(self.total_cents) is not int or self.total_cents <= 0
        ):
            raise ValueError("Your cost of attendance must be more than $0.")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort": self.cohort,
            "nonresident": self.nonresident,
            "insurance": self.insurance,
            "total_cents": self.total_cents,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CoaProfile:
        return cls(
            cohort=payload.get("cohort"),
            nonresident=payload.get("nonresident"),
            insurance=payload.get("insurance"),
            total_cents=payload.get("total_cents"),
        ).validate()


# What the student can settle by hand. Anything not pinned follows the ledger.
PINNABLE = ("housing", "cohort", "residency", "insurance")


@dataclass(frozen=True)
class BudgetSettings:
    housing: str = "Off-campus"
    # None is automatic; a number is the student's own line.
    weekly_cents: int | None = None
    bills: tuple[Bill, ...] = field(default_factory=tuple)
    # None until the ledger or the student says which cost of attendance is theirs.
    coa: CoaProfile | None = None
    # Names from PINNABLE. Values that aren't pinned are only a fallback.
    pinned: tuple[str, ...] = ()
    # Keys of bills the app found that the student said aren't bills.
    dismissed: tuple[str, ...] = ()

    def validate(self) -> BudgetSettings:
        if set(self.pinned) - set(PINNABLE):
            raise ValueError("Unknown setting to keep.")
        if self.coa is not None:
            self.coa.validate()
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
                if bill.match:
                    continue
                if category in categories:
                    raise ValueError(f"{category} is used by two bills. Map it to one.")
                categories.add(category)
        return self

    @property
    def bill_categories(self) -> dict[str, str]:
        """Categories that are a bill as a whole, not just purchases of one name."""
        return {
            category: bill.name
            for bill in self.bills
            if not bill.match
            for category in bill.categories
        }

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
                    "pinned": bill.pinned,
                    "match": sorted(bill.match),
                }
                for bill in self.bills
            ],
            "coa": self.coa.to_dict() if self.coa else None,
            "pinned": list(self.pinned),
            "dismissed": list(self.dismissed),
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
                    pinned=item.get("pinned", False),
                    match=frozenset(item.get("match", ())),
                )
                for item in payload.get("bills", ())
            ),
            coa=CoaProfile.from_dict(payload["coa"]) if payload.get("coa") else None,
            # Saved before anything was automatic: those values become fallbacks.
            pinned=tuple(payload.get("pinned", ())),
            dismissed=tuple(payload.get("dismissed", ())),
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
            dismissed=tuple(
                f"{key[: -len(source)]}{name}" if key.split("|", 2)[2:] == [source] else key
                for key in self.dismissed
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
    reference = payload.get("reference", {})
    coa = None
    if reference.get("cohort") in UCLA_2026["cohorts"] and reference.get("residency") in (
        "CA resident",
        "Nonresident",
    ):
        coa = CoaProfile(reference["cohort"], reference["residency"] == "Nonresident")
    return BudgetSettings(
        housing=housing if housing in HOUSING else "Off-campus", bills=tuple(bills), coa=coa
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


@cache
def school_periods() -> tuple[Period, ...]:
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
    return tuple(result)


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


# UCLA's calendar keeps its weekdays from one year to the next.
CALENDAR_YEAR = timedelta(days=364)


@cache
def _published_years() -> dict[tuple[date, date], tuple[date, ...]]:
    """The first day of fall, winter and spring in each published school year."""
    quarters = [p for p in school_periods() if p.kind == "quarter"]
    years: dict[tuple[date, date], tuple[date, ...]] = {}
    for index, period in enumerate(quarters):
        span = school_year_for(period.start)
        if period.name.startswith("Fall") and span:
            begins = [q.quarter_begins for q in quarters[index : index + 3]]
            years[span] = tuple(day for day in begins if day)
    return years


def quarter_starts(span: tuple[date, date]) -> tuple[date, ...]:
    """The day each quarter of a school year begins: fall, winter, spring."""
    years = _published_years()
    if span in years:
        return years[span]
    nearest = min(years, key=lambda known: abs((known[0] - span[0]).days))
    return tuple(day + (span[0] - nearest[0]) for day in years[nearest])


def school_years_back_to(span: tuple[date, date], first: date) -> list[tuple[date, date]]:
    """``span`` and the school years before it that reach ``first``, newest first.

    Years older than the published calendar repeat its earliest one, which is
    close enough to learn from and is never shown.
    """
    result = [span]
    while True:
        start, end = result[-1]
        before = school_year_for(start - timedelta(days=150))
        before = before or (start - CALENDAR_YEAR, end - CALENDAR_YEAR)
        if before[1] < first:
            return result
        result.append(before)


def _years_outside(day: date) -> int:
    """How many calendar years ``day`` lies before (negative) or after the published ones."""
    periods = school_periods()
    years = 0
    while day - CALENDAR_YEAR * years < periods[0].start:
        years -= 1
    while day - CALENDAR_YEAR * years > periods[-1].end:
        years += 1
    return years


def learning_span(day: date) -> tuple[date, date] | None:
    """``school_year_for`` any day, reading older and later ones off the published years."""
    shift = CALENDAR_YEAR * _years_outside(day)
    span = school_year_for(day - shift)
    return (span[0] + shift, span[1] + shift) if span else None


@cache
def _kind(day: date) -> str | None:
    at = day - CALENDAR_YEAR * _years_outside(day)
    return next((p.kind for p in school_periods() if p.start <= at <= p.end), None)


def learning_kind() -> Callable[[date], str | None]:
    """``period_kind_lookup`` for any day, reading older and later ones off the known years."""
    return _kind


def school_weeks() -> int:
    """Weeks in the preset's school year (fall week 0 through spring finals)."""
    year = UCLA_2026["academic_year"][:4]
    fall = next(p for p in school_periods() if p.name == f"Fall quarter {year}")
    span = school_year_for(fall.start)
    assert span is not None
    return ((span[1] - span[0]).days + 1) // 7


# ── Budget ────────────────────────────────────────────────────────────────


def weekly_line(settings: BudgetSettings, safe_cents: int | None = None) -> dict[str, Any]:
    """This week's line. ``safe_cents`` is what keeps the year inside the cost of attendance."""
    components = everyday_estimate(settings.housing)
    yearly = sum(components[name] for name in components if name != "Books")
    weeks = school_weeks()
    school = round(yearly / weeks)
    tightened = safe_cents is not None and safe_cents < school
    return {
        "weekly": settings.weekly_cents or (safe_cents if tightened else school),
        "source": "own" if settings.weekly_cents else "coa" if tightened else "school",
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
    return [due for due in _cadence_dues(bill, period) if bill.since is None or due >= bill.since]


def _cadence_dues(bill: Bill, period: Period) -> list[date]:
    if bill.dates:
        return [due for due in bill.dates if period.start <= due <= period.end]
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


def _monthly_due(month: date, due_day: int) -> date:
    return month.replace(day=min(due_day, calendar.monthrange(month.year, month.month)[1]))


def _paid_window(bill: Bill, due: date) -> tuple[date, date]:
    """The days whose payments count toward this due date.

    A monthly bill takes the payments nearer to this due date than to the one
    before or after, so rent paid on the 30th settles the bill due on the 1st.
    """
    if bill.cadence != "Monthly":
        return due - PAID_WINDOW, due + PAID_WINDOW
    first = due.replace(day=1)
    before = _monthly_due((first - timedelta(days=1)).replace(day=1), bill.due_day)
    after = _monthly_due((first + timedelta(days=32)).replace(day=1), bill.due_day)
    return (
        before + timedelta(days=(due - before).days // 2 + 1),
        due + timedelta(days=(after - due).days // 2),
    )


def _due_item(bill: Bill, due: date, spending: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    """One due date: what was paid toward it and where that leaves it."""
    start, end = _paid_window(bill, due)
    paid = sum(
        net(row)
        for row in spending
        if start.isoformat() <= _day(row) <= min(end, as_of).isoformat() and bill.pays(row)
    )
    # Tax and rounding move a bill by cents, so near the amount is paid.
    if paid > 0 and paid >= bill.amount_cents * (LEARNED_SHARE if bill.key else PAID_SHARE):
        status = "paid"
    elif paid > 0:
        status = "part"
    elif due + timedelta(days=bill.grace) < as_of:
        status = "late"
    elif due <= as_of + timedelta(days=7):
        status = "soon"
    else:
        status = "upcoming"
    return {
        "name": bill.name,
        "amount": bill.amount_cents,
        "due": due,
        "paid": paid,
        "status": status,
        "categories": list(bill.categories),
        "cadence": bill.cadence,
        "window_start": start,
        "window_end": end,
        "learned": bool(bill.key),
    }


def _bills(
    settings: BudgetSettings, spending: list[dict[str, Any]], period: Period, as_of: date
) -> list[dict[str, Any]]:
    """Every due date in the period: what needs attention first, settled ones last."""
    result = [
        _due_item(bill, due, spending, as_of)
        for bill in settings.bills
        for due in _bill_dues(bill, period)
    ]
    # An unpaid due date before one that is already paid was most likely paid
    # too and never recorded, so it stops asking for attention.
    settled: dict[str, date] = {}
    for item in result:
        if item["status"] == "paid":
            settled[item["name"]] = max(item["due"], settled.get(item["name"], item["due"]))
    for item in result:
        if item["status"] == "late" and item["due"] < settled.get(item["name"], date.min):
            item["status"] = "missed"
    order = {"late": 0, "part": 0, "soon": 1, "upcoming": 1, "paid": 2, "missed": 2}
    return sorted(
        result,
        key=lambda item: (
            order[item["status"]],
            -item["due"].toordinal() if order[item["status"]] == 2 else item["due"].toordinal(),
        ),
    )


def school_year_dues(bill: Bill, span: tuple[date, date]) -> list[date]:
    """The due dates that belong to a school year, oldest first.

    A monthly bill pays for the month that follows its due date, so it belongs
    once a third of that month is in the school year: September's rent counts,
    and rent due after finals week has mostly begun does not.
    """
    start, end = span
    if bill.dates:
        return sorted(due for due in bill.dates if start - EARLY_WINDOW <= due <= end)
    if bill.cadence != "Monthly":
        return sorted(
            due
            for period in school_periods()
            if start <= period.start <= end
            for due in _bill_dues(bill, period)
        )
    dues = []
    month = (start.replace(day=1) - timedelta(days=1)).replace(day=1)
    while month <= end:
        due = _monthly_due(month, bill.due_day)
        month = (month + timedelta(days=32)).replace(day=1)
        following = _monthly_due(month, bill.due_day)
        covered = (min(following - timedelta(days=1), end) - max(due, start)).days + 1
        if covered >= MONTH_SHARE_DAYS and (bill.since is None or due >= bill.since):
            dues.append(due)
    return dues


def school_year_bills(
    settings: BudgetSettings,
    spending: list[dict[str, Any]],
    span: tuple[date, date],
    as_of: date,
) -> list[tuple[Bill, dict[str, Any]]]:
    """Each bill's due dates in the school year, with what was paid toward them."""
    return [
        (bill, _due_item(bill, due, spending, as_of))
        for bill in settings.bills
        for due in school_year_dues(bill, span)
    ]


def next_due(bill: Bill, rows: list[dict[str, Any]], as_of: date) -> date | None:
    """The first due date nobody has paid yet, from a month back to a year ahead."""
    spending = [
        row
        for row in rows
        if row["transaction_type"] in ("expense", "refund") and _day(row) <= as_of.isoformat()
    ]
    first = as_of - PAID_WINDOW
    dues: list[date] = []
    if bill.dates or bill.cadence == "Once":
        dues = list(bill.dates) or ([bill.due] if bill.due else [])
    elif bill.cadence == "Each quarter":
        dues = [p.quarter_begins for p in school_periods() if p.quarter_begins]
    else:
        month = first.replace(day=1)
        for _ in range(14):
            dues.append(_monthly_due(month, bill.due_day))
            month = (month + timedelta(days=32)).replace(day=1)
    for due in sorted(dues):
        if due < first or (bill.since is not None and due < bill.since):
            continue
        item = _due_item(bill, due, spending, as_of)
        if item["status"] != "paid" and not (due < as_of and item["status"] == "part"):
            return due
    return None


def period_kind_lookup() -> Callable[[date], str | None]:
    """Name the kind of period a day falls in: quarter, break or summer.

    Days outside the published calendar have no kind.
    """
    periods = school_periods()

    def kind(day: date) -> str | None:
        return next((p.kind for p in periods if p.start <= day <= p.end), None)

    return kind


def term_budget(
    settings: BudgetSettings | None,
    rows: list[dict[str, Any]],
    as_of: date,
    rules: dict | None = None,
    day: date | None = None,
    lines: dict[date, int] | None = None,
) -> dict[str, Any]:
    """The weekly picture for the period holding ``day`` (default: today).

    ``lines`` holds the safe amount each Monday set, so a later, tighter line
    never turns an earlier week that was fine into one that wasn't.
    """
    settings = settings or BudgetSettings()
    lines = lines or {}
    this_week = monday(as_of)
    line = weekly_line(settings, lines.get(this_week))

    def line_for(week: date) -> int:
        return int(weekly_line(settings, lines.get(min(week, this_week)))["weekly"])

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
        weekly = line_for(start)
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

    bills = _bills(settings, spending, period, as_of)
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
            "line_to_date": sum(line_for(w) for w in completed),
            "saved": sum(line_for(w) - spent_between(w, w + timedelta(days=6)) for w in completed),
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
            "line_to_date": sum(w["line"] for w in weeks if w["state"] == "past"),
            "weeks_done": sum(w["state"] == "past" for w in weeks),
        },
        "bills": bills,
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
