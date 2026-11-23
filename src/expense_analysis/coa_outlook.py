"""Will the whole school year cost more than UCLA's cost of attendance?

The projection adds five layers, from what is certain to what is guessed:

1. ``recorded``: everything in the ledger that belongs to this school year.
2. ``due``: bills that are scheduled and not paid yet.
3. ``everyday``: a forecast of day-to-day spending through spring finals, plus
   regular costs nobody has set up as a bill.
4. ``one_offs``: flights and laptops, at the pace of the past year.
5. ``assumed``: tuition, insurance or housing the ledger does not show, counted
   at UCLA's own figure. Aid and family often pay these directly, and leaving
   them out would make the year look thousands cheaper than it is.

A cost belongs to the year it pays for, not the day it was paid: fall tuition
paid in August counts, and July's rent paid on June 12 does not.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from .forecast import (
    ONE_OFF_MINIMUM_WEEKS,
    RunRate,
    everyday_rate,
    one_off_rate,
    run_rate,
)
from .models import format_dollars
from .patterns import (
    BIG_CEILING,
    RENT_CENTS,
    SCHOOL_PARTS,
    Habits,
    Row,
    Span,
    coa_part,
    day_of,
    labelled_year,
)
from .spending_treatment import classify_spending
from .term_budget import (
    BudgetSettings,
    CoaProfile,
    learning_kind,
    monday,
    net,
    school_year_bills,
    school_year_for,
    school_years_back_to,
    weekly_line,
)
from .university_presets import (
    COA_ADJUSTMENT,
    EVERYDAY_COMPONENTS,
    UCLA_2026,
    coa_components,
)

REGULAR_HALF_LIFE = 26.0
MINIMUM_WEEKS = 4
HISTORY_WEEKS = 104
# Where trips and big purchases land, and how far UCLA's figure for that may be
# from one student's.
ONE_OFF_PARTS = ("Transportation", "Personal")
NEUTRAL_SPREAD = 0.4
# Housing under this share of UCLA's figure is utilities, not rent.
HOUSING_SEEN = 0.25
# A ledger this many days behind is caught up with the forecast.
STALE_DAYS = 6
Z80 = 1.2815515655446004
Z_LINE = 0.8416212335729143  # 80% one-sided, for a weekly amount to rely on
# School charges this close to UCLA's figure are complete, not missing something.
SCHOOL_SEEN = 0.9
OVER, UNDER = 0.8, 0.2

# How long before Week 0 a cost of each part is still this year's.
EARLY_PARTS = {
    "Tuition & fees": timedelta(days=45),
    "Health insurance": timedelta(days=100),
    "Books": timedelta(days=30),
    "Housing": timedelta(days=30),
}
# The flight to campus is booked over the summer.
EARLY_TRIP = timedelta(days=70)
LABELLED_PARTS = (*SCHOOL_PARTS, "Housing")
# Moving in starts a student's year a little before Week 0.
ARRIVAL_WINDOW, ARRIVAL_GAP, AWAY_GAP = 14, 5, 10


def split_cents(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Divide ``total`` by weight so the shares sum to it exactly."""
    positive = {name: weight for name, weight in weights.items() if weight > 0}
    whole = sum(positive.values())
    if not whole:
        return {"Personal": total} if total else {}
    shares = {name: total * weight // whole for name, weight in positive.items()}
    left = total - sum(shares.values())
    for name in sorted(positive, key=lambda n: -(total * positive[n] % whole))[:left]:
        shares[name] += 1
    return shares


def arrival(days: list[date], start: date) -> date:
    """The day the student moved in, if their spending picks up just before Week 0."""
    known = sorted(set(days))
    begun = start
    for day in reversed([d for d in known if start - timedelta(days=ARRIVAL_WINDOW) <= d < start]):
        if (begun - day).days > ARRIVAL_GAP:
            break
        begun = day
    away = any(begun - timedelta(days=AWAY_GAP) <= day < begun for day in known)
    return start if away else begun


def project(
    settings: BudgetSettings,
    rows: list[Row],
    as_of: date,
    rules: dict[str, Any] | None,
    span: Span,
    published: dict[str, int],
    habits: Habits,
) -> dict[str, Any]:
    """Everything one school year costs, recorded and still to come, in integer cents."""
    start, end = span
    saved_parts = (rules or {}).get("parts", {})

    def part_of(category: str) -> str:
        return coa_part(category, saved_parts)

    spending = [
        row
        for row in classify_spending(rows, settings, rules)
        if row["transaction_type"] in ("expense", "refund") and day_of(row) <= as_of
    ]
    recorded_days = [day_of(row) for row in spending]
    before = start - timedelta(days=1)
    latest = max(recorded_days, default=before)
    # Days after the last entry are not free days; they are not written down yet.
    through = max(before, latest if (as_of - latest).days > STALE_DAYS else as_of)
    stale = bool(recorded_days) and through < min(as_of, end)

    # ── Recorded and still due ────────────────────────────────────────────
    due_by_part: dict[str, int] = defaultdict(int)
    claimed: set[str] = set()
    # A payment toward a due date of this year, or of no year's.
    on_schedule: set[str] = {
        row["id"]
        for row in spending
        if any(bill.cadence == "Monthly" and bill.pays(row) for bill in settings.bills)
    }
    for bill, item in school_year_bills(settings, spending, span, as_of):
        if item["due"] < start and not item["paid"]:
            continue  # Nothing was paid before the year began, so nothing was owed.
        claimed.update(
            row["id"]
            for row in spending
            if item["window_start"] <= day_of(row) <= item["window_end"] and bill.pays(row)
        )
        # A smaller payment whose window has closed was the whole bill that time,
        # and a guess that never came true has lapsed.
        closed = item["window_end"] < as_of and (item["paid"] > 0 or bool(bill.key))
        if item["status"] != "paid" and not closed:
            part = part_of(bill.categories[0] if bill.categories else bill.name)
            due_by_part[part] += max(0, item["amount"] - max(0, item["paid"]))

    begun = arrival(
        [day_of(row) for row in spending if row["spending_treatment"] == "Everyday"], start
    )

    def counts(row: Row) -> bool:
        """Whether a purchase pays for this school year."""
        day, part = day_of(row), part_of(str(row["category"]))
        if part in LABELLED_PARTS and (labelled := labelled_year(row)) is not None:
            return labelled == start.year
        if row["id"] in claimed:
            return True
        if row["id"] in on_schedule:
            return False
        if day >= start:
            return day <= end
        if part in EARLY_PARTS:
            return day >= min(begun, start - EARLY_PARTS[part])
        if part == "Transportation" and row["spending_treatment"] != "Everyday":
            return day >= start - EARLY_TRIP
        return day >= begun

    recorded_by_part: dict[str, int] = defaultdict(int)
    early_by_part: dict[str, int] = defaultdict(int)
    for row in spending:
        if counts(row):
            part = part_of(str(row["category"]))
            recorded_by_part[part] += net(row)
            if day_of(row) < start:
                early_by_part[part] += net(row)

    # ── Forecast ──────────────────────────────────────────────────────────
    kind_of = learning_kind()
    ahead = [through + timedelta(days=i + 1) for i in range(max(0, (end - through).days))]
    streams: dict[str, dict[date, int]] = {
        "everyday": defaultdict(int),
        "regular": defaultdict(int),
        "one_offs": defaultdict(int),
    }
    stream_parts: dict[str, dict[str, int]] = {name: defaultdict(int) for name in streams}
    recent = through - timedelta(weeks=ONE_OFF_MINIMUM_WEEKS)
    for row in spending:
        day, part = day_of(row), part_of(str(row["category"]))
        if (
            row["id"] in habits.scheduled
            or row["id"] in claimed
            or row["id"] in on_schedule
            or row["category"] in settings.bill_categories
            or part in SCHOOL_PARTS
            # What names its school year is paid once for it, like a deposit.
            or (part in LABELLED_PARTS and labelled_year(row) is not None)
        ):
            continue
        treatment = row["spending_treatment"]
        stream = "everyday"
        if treatment == "Irregular":
            stream = "one_offs"
        elif treatment == "Commitments" or part == "Housing":
            # A large bill that doesn't repeat isn't a regular cost.
            stream = "one_offs" if int(row["amount_cents"]) >= BIG_CEILING else "regular"
        streams[stream][day] += net(row)
        if recent < day <= through or stream == "one_offs":
            stream_parts[stream][part] += net(row)
    weeks: list[date] = []
    gaps: list[date] = []
    if recorded_days:
        first = min(recorded_days)
        gaps += [
            start + timedelta(days=i)
            for i in range(max(0, (min(first, end + timedelta(days=1)) - start).days))
        ]
        active = {monday(day) for day in recorded_days}
        week = monday(first + timedelta(days=6))
        week = max(week, monday(through) - timedelta(weeks=HISTORY_WEEKS))
        while week + timedelta(days=6) <= through:
            # A week of classes with nothing at all written down is a gap, not a saving.
            if week in active or kind_of(week) != "quarter":
                weeks.append(week)
            elif start <= week <= end:
                gaps += [week + timedelta(days=i) for i in range(7)]
            week += timedelta(weeks=1)
    estimated = gaps + ahead

    line = weekly_line(settings)
    line_weekly = line["school_weekly"]
    if settings.housing == "On-campus" and recorded_by_part["Housing"] > 0:
        # The meal plan on the housing bill already pays for food.
        line_weekly -= round(published["Food"] / line["school_weeks"])
    from_history = len(weeks) >= MINIMUM_WEEKS
    if from_history:
        everyday = everyday_rate(
            *(streams["everyday"], weeks, estimated, kind_of, line_weekly),
            moved_on=habits.moved_on,
            year_starts=start,
        )
        # What was paid monthly before a move says nothing about after it.
        since = everyday.since or weeks[0]
        regular = run_rate(
            streams["regular"], [w for w in weeks if w >= since], estimated, REGULAR_HALF_LIFE
        )
    else:
        expected = line_weekly * len(estimated) / 7
        everyday = RunRate(expected, (expected * 0.25) ** 2, len(weeks), line_weekly)
        regular = RunRate(0.0, 0.0, len(weeks))
        stream_parts["everyday"] = {name: published[name] for name in EVERYDAY_COMPONENTS}
    if not from_history or not sum(max(0, v) for v in stream_parts["everyday"].values()):
        stream_parts["everyday"] = {name: published[name] for name in EVERYDAY_COMPONENTS}

    same_stretch = []
    if ahead and recorded_days:
        for past_start, past_end in school_years_back_to(span, min(recorded_days))[1:]:
            shift = start - past_start
            if ahead[0] - shift >= min(recorded_days):
                same_stretch.append(
                    sum(
                        amount
                        for day, amount in streams["one_offs"].items()
                        if ahead[0] - shift <= day <= past_end
                    )
                )
    school_time = [w for w in weeks if kind_of(w) != "summer"]
    # Until there is history, trips and big purchases are UCLA's figure for getting
    # around and personal costs, less what the everyday forecast already holds.
    figure = sum(published[part] for part in ONE_OFF_PARTS)
    figure_ahead = figure * len(estimated) / ((end - start).days + 1)
    held = split_cents(round(everyday.mean), stream_parts["everyday"])
    neutral = max(0.0, figure_ahead - sum(held.get(part, 0) for part in ONE_OFF_PARTS))
    trips = one_off_rate(
        streams["one_offs"],
        school_time,
        estimated,
        same_stretch,
        neutral,
        NEUTRAL_SPREAD * figure_ahead,
    )
    if not sum(max(0, v) for v in stream_parts["one_offs"].values()):
        stream_parts["one_offs"] = {part: published[part] for part in ONE_OFF_PARTS}
    means = {
        "everyday": round(everyday.mean),
        "regular": round(regular.mean),
        "one_offs": round(trips.mean),
    }
    forecast_by_part: dict[str, int] = defaultdict(int)
    for name, mean in means.items():
        for part, amount in split_cents(mean, stream_parts[name]).items():
            forecast_by_part[part] += amount

    # ── What the ledger does not show ─────────────────────────────────────
    notes: list[str] = []
    assumed_by_part: dict[str, int] = {}

    def known(part: str) -> int:
        return recorded_by_part[part] + due_by_part[part] + forecast_by_part[part]

    # One BruinBill payment often covers tuition, UC SHIP and a dorm room. What it
    # holds beyond UCLA's school charges pays for the others, not for nothing.
    bundled = max(0, known("Tuition & fees") - published["Tuition & fees"])
    if published["Health insurance"]:
        bundled += max(0, known("Health insurance") - published["Health insurance"])

    def assume(part: str) -> int:
        """Count the part at UCLA's figure, less what a bundled payment covers."""
        nonlocal bundled
        gap = max(0, published[part] - known(part))
        covered = min(gap, bundled)
        bundled -= covered
        if gap > covered:
            assumed_by_part[part] = gap - covered
        return assumed_by_part.get(part, 0)

    for part in SCHOOL_PARTS:
        # A charge the student's own records and schedule account for is complete,
        # whether or not it comes to UCLA's average.
        if known(part) >= SCHOOL_SEEN * published[part]:
            continue
        gap = assume(part)
        if gap:
            notes.append(
                f"{part}: {format_dollars(gap)} of UCLA's {format_dollars(published[part])} isn't "
                "recorded or scheduled, so it is added at UCLA's figure."
            )
    # A rent that small is still the rent; utilities alone are not.
    rent_known = any(
        bill.amount_cents >= RENT_CENTS
        and any(part_of(category) == "Housing" for category in bill.categories)
        for bill in settings.bills
    )
    if not rent_known and known("Housing") < HOUSING_SEEN * published["Housing"]:
        # A meal plan is billed with the room, so on campus the two go together.
        together = ("Housing", "Food") if settings.housing == "On-campus" else ("Housing",)
        for part in together:
            seen = known(part)
            if assume(part):
                notes.append(
                    f"{part}: only {format_dollars(seen)} is recorded or expected, so it is "
                    f"brought up to UCLA's {format_dollars(published[part])}."
                )
    if sum(early_by_part.values()):
        listed = ", ".join(
            f"{part} {format_dollars(amount)}"
            for part, amount in sorted(early_by_part.items(), key=lambda item: -item[1])
            if amount
        )
        notes.append(f"Paid before Week 0 and counted, because it is for this year: {listed}.")
    if everyday.since is not None and ahead:
        notes.append(
            f"Your everyday spending changed around {everyday.since:%b} {everyday.since.day}, so "
            "only the weeks since then set your pace."
        )
    if stale:
        notes.append(
            f"The last entry is {latest:%b} {latest.day}. The days since are estimated, not "
            "counted as free."
        )
    if gaps:
        notes.append(
            f"{len(gaps)} days of this school year have nothing recorded. They are estimated at "
            "your usual pace."
        )
    if ahead and not from_history:
        notes.append(
            f"There isn't a month of history yet, so everyday spending ahead uses UCLA's "
            f"{format_dollars(line_weekly)} a week."
        )
    if ahead and len(school_time) < ONE_OFF_MINIMUM_WEEKS:
        notes.append(
            "Trips and big purchases ahead lean on UCLA's transportation and personal figures "
            "until half a year is recorded."
        )

    recorded = sum(recorded_by_part.values())
    due = sum(due_by_part.values())
    assumed = sum(assumed_by_part.values())
    layers = {
        "recorded": recorded,
        "due": due,
        "everyday": means["everyday"] + means["regular"],
        "one_offs": means["one_offs"],
        "assumed": assumed,
    }
    parts = [
        {
            "part": part,
            "recorded": recorded_by_part[part],
            "projected": known(part) + assumed_by_part.get(part, 0),
            "assumed": assumed_by_part.get(part, 0),
        }
        for part in published
        if part != COA_ADJUSTMENT
    ]
    return {
        "through": through,
        "complete": not ahead,
        "layers": layers,
        "projected": sum(layers.values()),
        "floor": recorded + due + assumed,
        "variance": everyday.variance + regular.variance + trips.variance,
        # The part of the variance a student who keeps to a weekly amount still has.
        "other_variance": regular.variance + trips.variance,
        "typical": round(means["everyday"] * 7 / len(estimated)) if estimated else 0,
        "everyday_ahead": means["everyday"],
        "weeks_left": len(ahead) / 7,
        "history_weeks": len(weeks),
        "changed_on": everyday.since,
        "parts": parts,
        "notes": notes,
    }


def coa_outlook(
    settings: BudgetSettings | None,
    rows: list[Row],
    as_of: date,
    rules: dict[str, Any] | None = None,
    habits: Habits | None = None,
) -> dict[str, Any]:
    """Project the school year holding ``as_of`` and compare it with the COA line.

    ``ready`` is False with a ``reason`` when there is no line to compare with:
    ``year`` (UCLA's figures here are for another year) or ``profile`` (neither
    the ledger nor the student says which cost of attendance is theirs).
    """
    settings = settings or BudgetSettings()
    span = school_year_for(as_of)
    label = f"{span[0].year}–{str(span[0].year + 1)[2:]}" if span else None
    base = {
        "school": UCLA_2026["school"],
        "year": UCLA_2026["academic_year"],
        "source_url": UCLA_2026["source"],
        "verified_on": UCLA_2026["verified_on"],
    }
    if span is None or label != UCLA_2026["academic_year"]:
        return {**base, "ready": False, "reason": "year"}
    profile = settings.coa
    if profile is None or profile.cohort is None or profile.nonresident is None:
        return {**base, "ready": False, "reason": "profile"}
    habits = habits or Habits()
    published = published_for(profile, settings.housing)
    line = profile.total_cents or sum(published.values())
    year = project(settings, rows, as_of, rules, span, published, habits)

    projected, floor = year["projected"], year["floor"]
    margin = line - projected
    deviation = habits.spread * math.sqrt(year["variance"])
    if deviation > 0:
        chance = 0.5 * (1 + math.erf(-margin / deviation / math.sqrt(2)))
    else:
        chance = 1.0 if margin < 0 else 0.0
    band = round(Z80 * deviation)
    # Spending that already passes the line can only be undone by refunds.
    if floor > line:
        chance = 1.0
    verdict = "over" if chance >= OVER else "under" if chance <= UNDER else "close"
    weekly = None
    weeks_left = year["weeks_left"]
    if weeks_left:
        safe = round(year["typical"] + margin / weeks_left)
        cushion = Z_LINE * habits.spread * math.sqrt(year["other_variance"])
        weekly = {
            "typical": year["typical"],
            "safe": max(0, safe),
            # Leaves room for the trips and bills that can't be known yet.
            "sure": max(0, round(year["typical"] + (margin - cushion) / weeks_left)),
            "possible": safe >= 0,
            "weeks_left": round(weeks_left, 1),
        }

    by_part = {item["part"]: item for item in year["parts"]}
    merged = settings.housing == "On-campus"
    parts: list[dict[str, Any]] = []
    for part, item in by_part.items():
        if merged and part == "Food":
            continue
        members = ("Housing", "Food") if merged and part == "Housing" else (part,)
        expected = sum(by_part[m]["projected"] for m in members)
        limit = sum(published[m] for m in members)
        parts.append(
            {
                **item,
                "part": "Housing & food" if len(members) > 1 else part,
                "recorded": sum(by_part[m]["recorded"] for m in members),
                "projected": expected,
                "published": limit,
                "difference": limit - expected,
                "assumed": sum(by_part[m]["assumed"] for m in members),
            }
        )
    return {
        **base,
        "ready": True,
        "reason": None,
        "start": span[0],
        "end": span[1],
        "through": year["through"],
        "complete": year["complete"],
        "line": line,
        "own_total": profile.total_cents is not None,
        "adjustment": line - sum(item["published"] for item in parts),
        "layers": year["layers"],
        "projected": projected,
        "low": max(floor, projected - band),
        "high": projected + band,
        "margin": margin,
        "chance": chance,
        "verdict": verdict,
        "weekly": weekly,
        "changed_on": year["changed_on"],
        "history_weeks": year["history_weeks"],
        "parts": parts,
        "notes": year["notes"],
    }


def published_for(profile: CoaProfile, housing: str) -> dict[str, int]:
    """UCLA's figures for a profile; unknown insurance counts as UC SHIP."""
    profile = replace(profile, insurance=True if profile.insurance is None else profile.insurance)
    assert profile.cohort is not None and profile.nonresident is not None
    assert profile.insurance is not None
    return coa_components(profile.cohort, housing, profile.nonresident, profile.insurance)
