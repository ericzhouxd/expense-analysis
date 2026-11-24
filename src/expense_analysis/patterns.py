"""What the ledger itself shows: repeating charges, school charges, where the student lives.

Everything is worked out from the student's own rows each time it is asked for.
Nothing learned is stored and no amounts are built in, so there is no model file
to leak or go stale, and another student's ledger teaches it their habits.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from statistics import median
from typing import Any

from .models import keyword_matches, name_tokens, same_name
from .term_budget import EARLY_WINDOW, net, quarter_starts

Row = dict[str, Any]
Span = tuple[date, date]

SCHOOL_PARTS = ("Tuition & fees", "Health insurance")

# First match wins, so "car insurance" is transportation.
_PART_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Tuition & fees", ("tuition", "school fee", "campus fee", "student fee", "registration")),
    (
        "Transportation",
        ("transport", "transportation", "transit", "bus", "metro", "car", "auto", "gas", "fuel")
        + ("parking", "uber", "lyft", "rideshare", "flight", "airfare", "airline", "travel"),
    ),
    ("Health insurance", ("insurance", "ucship")),
    ("Housing", ("rent", "housing", "dorm", "utilities", "utility", "electric", "electricity")),
    ("Housing", ("internet", "wifi")),
    ("Food", ("food", "dining", "grocer", "grocery", "restaurant", "coffee", "meal", "snack")),
    ("Books", ("book", "textbook", "stationery", "school supplies", "course material")),
)

RENT_WORDS = ("rent", "lease", "apartment")
CAMPUS_WORDS = ("dorm", "dorms", "campus housing", "residence hall", "meal plan", "room and board")
UTILITY_WORDS = ("utilities", "utility", "electric", "electricity", "internet", "wifi")
BILL_WORDS = (
    *("tuition", "school fee", "campus fee", "student fee", "registration", "insurance"),
    *("rent", "housing", "dorm", "utilities", "utility", "electric", "electricity", "internet"),
    *("wifi", "phone", "mobile", "subscription", "membership"),
)
BIG_WORDS = (
    *("flight", "airfare", "airline", "hotel", "lodging", "airbnb", "travel", "trip"),
    *("vacation", "furniture", "laptop", "electronics", "medical", "dental", "doctor"),
)
# A prepaid plan says so; one payment is enough to expect the next one.
_YEAR_TERM = re.compile(r"\b(?:1|one)[ -]?(?:year|yr)\b|\bannual\b|\byearly\b|\b12[ -]?months?\b")
_SCHOOL_YEAR_LABEL = re.compile(r"(?<![\d/-])(?:20)?(\d{2})\s?[-/–]\s?(?:20)?(\d{2})(?![\d/-])")

# A quarter's tuition or room is at least this much.
SCHOOL_CHARGE_CENTS = 100_000
# Charges for one quarter post together; stray fees come on other days.
CHARGE_CLUSTER = timedelta(days=5)
QUARTER_BEFORE, QUARTER_AFTER = timedelta(days=60), timedelta(days=30)
# How long after a quarter begins an unpaid charge means it isn't coming.
QUARTER_GRACE = timedelta(days=21)
RENT_CENTS = 20_000
MONTHLY_GRACE = timedelta(days=45)
YEARLY_GRACE = timedelta(days=30)
# A purchase made twice, a year apart, is expected again from this amount.
YEARLY_CENTS = 7_500
# Purchases are big stuff from several times the usual one, within reason.
BIG_MULTIPLE, BIG_FLOOR, BIG_CEILING = 6, 7_500, 25_000
BIG_MINIMUM_PURCHASES = 20


@dataclass(frozen=True)
class Habits:
    """What the projection needs to know beyond settings and rules."""

    # Purchases that run on their own schedule or have stopped: never part of a pace.
    scheduled: frozenset[str] = frozenset()
    # When the student moved to a different kind of housing, if they did.
    moved_on: date | None = None
    # How much wider the range must be, going by earlier years' misses.
    spread: float = 1.0


def coa_part(category: str, parts: dict[str, str] | None = None) -> str:
    """The part of the cost of attendance a category counts toward."""
    return parts[category] if parts and category in parts else _part_by_name(category)


@lru_cache(maxsize=4096)
def _part_by_name(category: str) -> str:
    for part, keywords in _PART_KEYWORDS:
        if any(keyword_matches(keyword, category) for keyword in keywords):
            return part
    return "Personal"


def says(words: Iterable[str], text: str) -> bool:
    return any(keyword_matches(word, text) for word in words)


_parse_day = lru_cache(maxsize=8192)(date.fromisoformat)


def day_of(row: Row) -> date:
    return _parse_day(str(row["transaction_date"])[:10])


def description_of(row: Row) -> str:
    return str(row.get("description") or row.get("merchant") or "")


def labelled_year(row: Row) -> int | None:
    """The fall year a description names, as in ``Deposit 26-27``, if it makes sense."""
    bought = day_of(row)
    for match in _SCHOOL_YEAR_LABEL.finditer(description_of(row)):
        first, second = int(match.group(1)), int(match.group(2))
        year = 2000 + first
        if second == first + 1 and abs(year - bought.year) <= 1:
            return year
    return None


# ── Charges the school makes every quarter ────────────────────────────────


@dataclass(frozen=True)
class QuarterCharge:
    """What was paid for one quarter, and when."""

    total: int
    paid_on: date
    ids: frozenset[str]


def quarter_charges(rows: list[Row], spans: list[Span]) -> dict[tuple[Span, int], QuarterCharge]:
    """The main payment for each quarter, keyed by school year and quarter number.

    A quarter's charges post together, so the largest day and the days around it
    are the charge; a late fee in another month is not.
    """
    starts = [(span, at, day) for span in spans for at, day in enumerate(quarter_starts(span))]
    grouped: dict[tuple[Span, int], list[Row]] = defaultdict(list)
    for row in rows:
        day = day_of(row)
        near = [
            (abs((day - begins).days), span, at)
            for span, at, begins in starts
            if begins - QUARTER_BEFORE <= day <= begins + QUARTER_AFTER
        ]
        if near:
            _, span, at = min(near)
            grouped[span, at].append(row)
    result = {}
    for key, members in grouped.items():
        by_day: dict[date, int] = defaultdict(int)
        for row in members:
            by_day[day_of(row)] += net(row)
        main = max(by_day, key=lambda day: by_day[day])
        cluster = [row for row in members if abs(day_of(row) - main) <= CHARGE_CLUSTER]
        total = sum(net(row) for row in cluster)
        if total >= SCHOOL_CHARGE_CENTS:
            result[key] = QuarterCharge(total, main, frozenset(row["id"] for row in cluster))
    return result


@dataclass(frozen=True)
class SchoolBill:
    """A quarterly charge this school year: what the next one costs and when."""

    amount: int
    dates: tuple[date, ...]
    paid: int
    why: str


def _year_later(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # Feb 29
        return day.replace(year=day.year + 1, day=28)


def school_bill(
    charges: dict[tuple[Span, int], QuarterCharge], span: Span, as_of: date
) -> SchoolBill | None:
    """The rest of this year's quarterly charges, judged from the ones already paid.

    Amounts follow this year's latest charge and last year's same quarters. Due
    dates follow last year's payments. A quarter that went unpaid means the
    school is not charging this student (any more).
    """
    before = max((key[0] for key in charges if key[0] < span), default=None)
    last_year = {at: charges[before, at] for at in range(3) if before and (before, at) in charges}
    this_year = {at: charges[span, at] for at in range(3) if (span, at) in charges}
    starts = quarter_starts(span)
    for at, begins in enumerate(starts):
        if at not in this_year and begins + QUARTER_GRACE < as_of:
            return None
    if not this_year and not last_year:
        return None
    left = [at for at in range(3) if at not in this_year]
    if this_year:
        latest = max(this_year)
        base, like = this_year[latest].total, last_year.get(latest)
    else:
        latest = max(last_year)
        base, like = last_year[latest].total, last_year[latest]
    # One-time fees can distort any one of these; the middle of the three ignores them.
    amounts = [
        round(
            median((base, base * last_year[at].total / like.total, last_year[at].total))
            if like and at in last_year
            else base
        )
        for at in left
    ]
    due = [
        _year_later(last_year[at].paid_on) if at in last_year else starts[at] - timedelta(days=14)
        for at in left
    ]
    paid = [charge.paid_on for charge in charges.values()]
    count = len(paid)
    why = f"{count} quarterly payment{'' if count == 1 else 's'}"
    if left and last_year:
        why += ", timed like last year"
    return SchoolBill(
        amount=round(sum(amounts) / len(amounts)) if amounts else base,
        dates=tuple(sorted([*paid, *due])),
        paid=len(this_year),
        why=why,
    )


# ── Charges that repeat by the month or the year ──────────────────────────


@dataclass(frozen=True)
class Series:
    """Purchases of the same thing on a cycle."""

    name: str
    category: str
    tokens: frozenset[str]
    cadence: str  # Monthly | Yearly
    amount: int
    due_day: int
    next_due: date
    first: date
    last: date
    paid_on: tuple[date, ...]
    ids: frozenset[str]
    active: bool
    # Nothing else is bought in this category, so all of it is the bill.
    whole_category: bool

    @property
    def count(self) -> int:
        return len(self.paid_on)


def circular_day(days: list[int]) -> int:
    """The middle of some days of the month, where the 30th and the 2nd are neighbors."""
    angles = [2 * math.pi * day / 30.44 for day in days]
    x = sum(math.cos(angle) for angle in angles)
    y = sum(math.sin(angle) for angle in angles)
    middle = math.atan2(y, x) / (2 * math.pi) * 30.44
    return min(31, max(1, round(middle if middle > 0.5 else middle + 30.44)))


def _spread_days(days: list[int], middle: int) -> float:
    return max(min(abs(day - middle), 30.44 - abs(day - middle)) for day in days)


def _typical(amounts: list[int]) -> int:
    """The latest amount once it repeats, otherwise the middle of the last three."""
    if len(amounts) > 1 and abs(amounts[-1] - amounts[-2]) <= 0.02 * amounts[-1]:
        return amounts[-1]
    return round(median(amounts[-3:]))


def repeating_charges(rows: list[Row], as_of: date, skip: frozenset[str]) -> list[Series]:
    """Find what repeats monthly or yearly, including what has since stopped."""
    expenses = sorted(
        (
            row
            for row in rows
            if row["transaction_type"] == "expense"
            and row["id"] not in skip
            and day_of(row) <= as_of
        ),
        key=day_of,
    )
    groups: list[tuple[str, frozenset[str], list[Row]]] = []
    by_category: dict[str, list[int]] = defaultdict(list)
    prepaid: list[Row] = []
    for row in expenses:
        category = str(row["category"])
        text = description_of(row)
        if _YEAR_TERM.search(text.casefold()):
            prepaid.append(row)
            continue
        tokens = name_tokens(category if says(RENT_WORDS, category) else text)
        for index in by_category[category]:
            if same_name(tokens, groups[index][1]):
                groups[index][2].append(row)
                break
        else:
            by_category[category].append(len(groups))
            groups.append((category, tokens, [row]))
    recent = as_of - timedelta(days=120)
    recent_count: dict[str, int] = defaultdict(int)
    for row in expenses:
        if day_of(row) >= recent:
            recent_count[str(row["category"])] += 1

    result: list[Series] = []
    for row in prepaid:
        category, tokens = str(row["category"]), name_tokens(description_of(row))
        tokens -= {"year", "yr", "one", "annual", "yearly", "month", "months"}
        later = any(
            day_of(other) > day_of(row)
            and other["category"] == category
            and same_name(tokens, name_tokens(description_of(other)))
            for other in prepaid
        )
        due = _year_later(day_of(row))
        terms = sorted(
            day_of(other)
            for other in prepaid
            if other["category"] == category
            and day_of(other) <= day_of(row)
            and same_name(tokens, name_tokens(description_of(other)))
        )
        # The same service paid by the month before is over, not a second cost.
        same = {
            other["id"]
            for other in expenses
            if other["category"] == category
            and day_of(other) <= day_of(row)
            and same_name(tokens, name_tokens(description_of(other)))
        }
        result.append(
            Series(
                name=description_of(row),
                category=category,
                tokens=tokens,
                cadence="Yearly",
                amount=int(row["amount_cents"]),
                due_day=due.day,
                next_due=due,
                first=terms[0] if terms else day_of(row),
                last=day_of(row),
                paid_on=tuple(terms) or (day_of(row),),
                ids=frozenset({row["id"], *same}),
                active=not later and due + YEARLY_GRACE >= as_of,
                whole_category=False,
            )
        )
    for category, tokens, members in groups:
        found = _monthly(category, tokens, members, as_of) or _yearly(
            category, tokens, members, as_of
        )
        if found is None:
            continue
        replaced = any(
            item.cadence == "Yearly"
            and item.category == category
            and item.last > found.last
            and same_name(item.tokens, tokens)
            for item in result
        )
        mine = sum(1 for row in members if day_of(row) >= recent)
        result.append(
            Series(
                **{
                    **found.__dict__,
                    "active": found.active and not replaced,
                    "whole_category": found.cadence == "Monthly"
                    and mine > 0
                    and mine == recent_count[category]
                    and says(BILL_WORDS, category),
                }
            )
        )
    return result


def _monthly(category: str, tokens: frozenset[str], rows: list[Row], as_of: date) -> Series | None:
    by_day: dict[date, int] = defaultdict(int)
    for row in rows:
        by_day[day_of(row)] += int(row["amount_cents"])
    days = sorted(by_day)[-6:]
    amounts = [by_day[day] for day in days]
    text = f"{category} {' '.join(tokens)}"
    bill = says(BILL_WORDS, text)
    # Rent is monthly by nature, so one payment already says what comes next.
    rent = says(RENT_WORDS, category) and min(amounts) >= RENT_CENTS
    if len(days) < (1 if rent else 2 if bill else 3):
        return None
    last = days[-1]
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)][-3:]
    if gaps and not (all(18 <= gap <= 48 for gap in gaps) and 25 <= median(gaps) <= 38):
        return None
    steady = amounts[-3:]
    if max(steady) > min(steady) * (1.35 if bill else 1.02):
        return None
    middle = circular_day([day.day for day in days])
    # A weekly habit can land a month apart by chance; a subscription keeps its day.
    if not bill and _spread_days([day.day for day in days], middle) > 4:
        return None
    if rent and (middle >= 24 or middle <= 7):
        middle = 1
    following = last + timedelta(days=31)
    return Series(
        name=category if rent else description_of(rows[-1]),
        category=category,
        tokens=tokens,
        cadence="Monthly",
        # A first month's rent is often prorated, so the latest payment is the rent.
        amount=amounts[-1] if rent else _typical(amounts),
        due_day=middle,
        next_due=following,
        first=min(by_day),
        last=last,
        paid_on=tuple(sorted(by_day)),
        ids=frozenset(row["id"] for row in rows),
        active=last + MONTHLY_GRACE >= as_of,
        whole_category=False,
    )


def _yearly(category: str, tokens: frozenset[str], rows: list[Row], as_of: date) -> Series | None:
    days = [day_of(row) for row in rows]
    amounts = [int(row["amount_cents"]) for row in rows]
    bill = says(BILL_WORDS, category)
    if len(rows) < 2 or (not bill and min(amounts[-2:]) < YEARLY_CENTS):
        return None
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    if not all((300 if bill else 340) <= gap <= 400 for gap in gaps):
        return None
    if max(amounts[-2:]) > min(amounts[-2:]) * (1.4 if bill else 1.25):
        return None
    due = _year_later(days[-1])
    return Series(
        name=description_of(rows[-1]),
        category=category,
        tokens=tokens,
        cadence="Yearly",
        amount=amounts[-1],
        due_day=due.day,
        next_due=due,
        first=days[0],
        last=days[-1],
        paid_on=tuple(days),
        ids=frozenset(row["id"] for row in rows),
        active=due + YEARLY_GRACE >= as_of,
        whole_category=False,
    )


# ── Where the student lives, and what counts as a big purchase ────────────


def rent_payments(rows: list[Row], as_of: date) -> list[Row]:
    """The housing payments that are rent, not utilities or the school's room charge.

    ``rows`` are all the student's housing costs. Rent says so or repeats by the
    month; the school charges for a room by the quarter.
    """
    likely = [
        row
        for row in rows
        if row["transaction_type"] == "expense"
        and int(row["amount_cents"]) >= RENT_CENTS
        and not says((*CAMPUS_WORDS, *UTILITY_WORDS), f"{row['category']} {description_of(row)}")
    ]
    by_month = {
        identifier
        for item in repeating_charges(likely, as_of, frozenset())
        if item.cadence == "Monthly"
        for identifier in item.ids
    }
    return [
        row
        for row in likely
        if row["id"] in by_month or says(RENT_WORDS, f"{row['category']} {description_of(row)}")
    ]


def housing_in(
    span: Span,
    room: dict[tuple[Span, int], QuarterCharge],
    rent: list[Row],
    as_of: date,
) -> tuple[str, str] | None:
    """Housing type and the evidence for it in one school year, if the ledger shows any."""
    start, end = span
    rooms = [charge for key, charge in room.items() if key[0] == span and charge.paid_on <= as_of]
    rents = [row for row in rent if start - EARLY_WINDOW <= day_of(row) <= min(end, as_of)]
    paid_room = sum(charge.total for charge in rooms)
    paid_rent = sum(net(row) for row in rents)
    if paid_room and paid_room >= paid_rent:
        count = len(rooms)
        return "On-campus", f"{count} housing payment{'' if count == 1 else 's'} to the school"
    if paid_rent:
        first = min(day_of(row) for row in rents)
        return "Off-campus", f"rent paid since {first:%b} {first.day}, {first.year}"
    return None


def big_purchase(rows: list[Row], as_of: date) -> int:
    """The amount, in cents, from which an ordinary purchase is big stuff."""
    recent = as_of - timedelta(days=730)
    amounts = [
        int(row["amount_cents"])
        for row in rows
        if row["transaction_type"] == "expense" and recent < day_of(row) <= as_of
    ]
    if len(amounts) < BIG_MINIMUM_PURCHASES:
        return 10_000
    return int(min(BIG_CEILING, max(BIG_FLOOR, BIG_MULTIPLE * median(amounts))))


def lumpy(amounts: list[int], days: int, usual: float) -> bool:
    """Whether a category holds few, large purchases rather than day-to-day ones."""
    if len(amounts) < 3 or days <= 0:
        return False
    return median(amounts) >= max(6_000, 4 * usual) and len(amounts) / days * 30.44 < 2
