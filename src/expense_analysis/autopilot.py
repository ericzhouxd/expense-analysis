"""Budget settings worked out from the ledger, so there is nothing to set up.

``resolve`` fills in everything the budget needs: where the student lives, which
cost of attendance is theirs, the bills and how each purchase counts. Order of
trust: what the student pinned, what the ledger shows, what was saved before,
then a default. Every answer carries its source and the reason for it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import median
from typing import Any

from .models import format_dollars, keyword_matches, same_name
from .patterns import (
    BIG_WORDS,
    BILL_WORDS,
    Habits,
    QuarterCharge,
    Row,
    Series,
    Span,
    big_purchase,
    coa_part,
    day_of,
    description_of,
    housing_in,
    lumpy,
    quarter_charges,
    rent_payments,
    repeating_charges,
    says,
    school_bill,
)
from .spending_treatment import TREATMENTS
from .term_budget import (
    PINNABLE,
    Bill,
    BudgetSettings,
    CoaProfile,
    learning_span,
    school_years_back_to,
)
from .university_presets import UCLA_2026

# How far a quarter's charges may be from UCLA's and still be recognized.
PROFILE_TOLERANCE, PROFILE_TOLERANCE_CENTS = 0.04, 50_000
# An answer other evidence points away from must fit this much better to win.
AGAINST_EVIDENCE_CENTS = 15_000
OWN_PLAN_WINDOW = timedelta(days=400)
ENTRY_WINDOW = 90
SHIP_WORDS = ("uc ship", "ucship", "ship")
# A guessed due date may be this many days off before a payment looks missing.
LEARNED_GRACE = 7
NEVER_BIG_PARTS = ("Food",)
DEFAULT_HOUSING = BudgetSettings().housing


@dataclass(frozen=True)
class Fact:
    """One answer, where it came from and why, and what the automatic one would be."""

    key: str
    label: str
    value: Any
    text: str
    source: str  # yours | learned | earlier | default
    why: str
    auto_text: str
    auto_why: str


@dataclass(frozen=True)
class CategoryAnswer:
    treatment: str
    pinned: bool
    part: str
    part_pinned: bool
    why: str


@dataclass(frozen=True)
class AutoBudget:
    """Complete settings and rules, ready for the budget modules."""

    settings: BudgetSettings
    rules: dict[str, Any]
    facts: tuple[Fact, ...]
    categories: dict[str, CategoryAnswer]
    big_cents: int
    habits: Habits
    # Found, but the student said they aren't bills.
    dismissed: tuple[Bill, ...]


def legacy_suggestion(category: str, fixed: Iterable[str]) -> str:
    """What the settings table used to fill in for a category."""
    if category in fixed:
        return "Commitments"
    if category.casefold() in ("flights", "flight", "airfare", "travel"):
        return "Irregular"
    return "Everyday"


def pinned_treatments(rules: dict[str, Any], fixed: Iterable[str]) -> dict[str, str]:
    """The category choices that are really the student's.

    The table used to save every suggestion together with the student's choices.
    From then, only what differs from the suggestion was a choice.
    """
    saved = dict(rules.get("categories", {}))
    if rules.get("auto"):
        return saved
    fixed = frozenset(fixed)
    return {
        category: treatment
        for category, treatment in saved.items()
        if treatment != legacy_suggestion(category, fixed)
    }


def infer_profile(
    charges: dict[tuple[Span, int], QuarterCharge],
    first_day: date,
    hint: str | None,
    ship: bool | None,
) -> tuple[str, bool, bool, str] | None:
    """Entry year, residency and UC SHIP that best explain the latest tuition payment.

    Entry years differ by about as much as UC SHIP costs, so a close call goes to
    ``hint`` (an earlier answer), or else the first year with tuition in the
    ledger, and to what insurance purchases say (``ship``).
    """
    if not charges:
        return None
    (span, at), latest = max(charges.items(), key=lambda item: item[0])
    earliest = min(key[0] for key in charges)
    likely = hint
    # Only a ledger that starts with a school year hints at the year of entry.
    if likely is None and abs((first_day - earliest[0]).days) <= ENTRY_WINDOW:
        likely = f"{earliest[0].year}–{str(earliest[0].year + 1)[2:]}"
    best: tuple[float, float, str, bool, bool, float] | None = None
    for cohort, rates in UCLA_2026["cohorts"].items():
        if int(cohort[:4]) > span[0].year:
            continue
        for nonresident in (False, True):
            for insured in (False, True):
                yearly = rates["tuition"] + UCLA_2026["campus_fees"]
                yearly += rates["nrst"] if nonresident else 0
                yearly += UCLA_2026["insurance"] if insured else 0
                miss = abs(latest.total - yearly / 3)
                score = miss
                score += AGAINST_EVIDENCE_CENTS if likely and cohort != likely else 0
                score += AGAINST_EVIDENCE_CENTS if ship is not None and insured != ship else 0
                option = (score, miss, cohort, nonresident, insured, yearly / 3)
                best = option if best is None or option < best else best
    if best is None:
        return None
    _, miss, cohort, nonresident, insured, expected = best
    if miss > max(PROFILE_TOLERANCE_CENTS, PROFILE_TOLERANCE * expected):
        return None
    name = ("Fall", "Winter", "Spring")[at]
    why = (
        f"{name} tuition and fees of {format_dollars(latest.total)} fit UCLA's "
        f"{format_dollars(round(expected))} a quarter"
    )
    return cohort, nonresident, insured, why


def _pick(
    key: str,
    label: str,
    settings: BudgetSettings | None,
    saved: Any,
    learned: tuple[Any, str] | None,
    default: Any,
    text: dict[Any, str] | None = None,
) -> Fact:
    """Choose one answer by trust and say where it came from."""

    def shown(value: Any) -> str:
        return "Unknown" if value is None else (text or {}).get(value, str(value))

    pinned = settings is not None and key in settings.pinned and saved is not None
    if learned:
        (value, why), source = learned, "learned"
    elif saved is not None and not pinned:
        value, source, why = saved, "earlier", "from your earlier settings"
    else:
        value, source, why = default, "default", "nothing in your records shows it yet"
    auto_text, auto_why = shown(value), why
    if pinned:
        value, source, why = saved, "yours", "you chose this"
    return Fact(key, label, value, shown(value), source, why, auto_text, auto_why)


def _unique(name: str, taken: set[str]) -> str:
    result, number = name, 2
    while result in taken:
        result, number = f"{name} {number}", number + 1
    taken.add(result)
    return result


def _series_key(item: Series) -> str:
    # The category comes last because a name may hold any character.
    return f"{item.cadence}|{' '.join(sorted(item.tokens))}|{item.category}"


def _series_bill(item: Series) -> Bill:
    if item.cadence == "Yearly":
        times = "a one-year plan" if item.count == 1 else f"{item.count} payments a year apart"
        return Bill(
            name=item.name,
            amount_cents=item.amount,
            categories=(item.category,),
            cadence="Once",
            due=item.next_due,
            key=_series_key(item),
            why=f"{times}, the last on {item.last:%b} {item.last.day}, {item.last.year}",
            match=item.tokens,
            dates=(*item.paid_on, item.next_due),
            grace=LEARNED_GRACE,
        )
    month = item.first.replace(day=1)
    if item.first.day > item.due_day + 15:
        month = (month + timedelta(days=32)).replace(day=1)
    return Bill(
        name=item.name,
        amount_cents=item.amount,
        categories=(item.category,),
        cadence="Monthly",
        due_day=item.due_day,
        key=_series_key(item),
        why=f"{item.count} monthly payments, the last on {item.last:%b} {item.last.day}",
        match=frozenset() if item.whole_category else item.tokens,
        since=month,
        grace=LEARNED_GRACE,
    )


def _replaces(own: Bill, learned: Bill) -> bool:
    """Whether the student's own bill is the same one the ledger shows."""
    if not set(own.categories) & set(learned.categories):
        return False
    return not own.match or same_name(own.match, learned.match)


def resolve(
    saved: BudgetSettings | None,
    rules: dict[str, Any] | None,
    rows: list[Row],
    as_of: date,
    fixed: Iterable[str] = (),
) -> AutoBudget:
    """Everything the budget needs, from the ledger as it stood on ``as_of``."""
    rules = rules or {}
    fixed = frozenset(fixed)
    settings = saved or BudgetSettings()
    saved_parts = rules.get("parts", {})

    def part_of(category: str) -> str:
        return coa_part(category, saved_parts)

    spending = [
        row
        for row in rows
        if row["transaction_type"] in ("expense", "refund") and day_of(row) <= as_of
    ]
    first_day = min((day_of(row) for row in spending), default=as_of)
    span = learning_span(as_of)
    spans = school_years_back_to(span, first_day) if span else []

    by_part: dict[str, list[Row]] = defaultdict(list)
    for row in spending:
        by_part[part_of(str(row["category"]))].append(row)
    tuition = quarter_charges(by_part["Tuition & fees"], spans)
    rent = rent_payments(by_part["Housing"], as_of)
    not_room = {row["id"] for row in rent}
    room = quarter_charges([r for r in by_part["Housing"] if r["id"] not in not_room], spans)
    school_ids = frozenset(
        identifier for charge in (*tuition.values(), *room.values()) for identifier in charge.ids
    )
    series = repeating_charges(spending, as_of, school_ids)

    # ── Where they live and which cost of attendance is theirs ────────────
    learned_housing = housing_in(span, room, rent, as_of) if span else None
    earlier_housing = housing_in(spans[1], room, rent, as_of) if len(spans) > 1 else None
    moved_on = None
    if span and learned_housing and earlier_housing and learned_housing[0] != earlier_housing[0]:
        moved_on = span[0]
    pinned_housing = "housing" in settings.pinned
    housing = _pick(
        "housing",
        "Where you live",
        saved,
        # Settings always hold a value, so the first choice in the list says nothing.
        settings.housing if pinned_housing or settings.housing != DEFAULT_HOUSING else None,
        learned_housing,
        DEFAULT_HOUSING,
    )
    own_plan = [
        row
        for row in by_part["Health insurance"]
        if row["transaction_type"] == "expense"
        and day_of(row) >= as_of - OWN_PLAN_WINDOW
        and not says(SHIP_WORDS, f"{row['category']} {description_of(row)}")
    ]
    ship_named = any(
        keyword_matches(word, description_of(row))
        for row in (*by_part["Tuition & fees"], *by_part["Health insurance"])
        for word in SHIP_WORDS
        if day_of(row) >= as_of - OWN_PLAN_WINDOW
    )
    hint = settings.coa or CoaProfile()
    ship = True if ship_named else False if own_plan else None
    profile = infer_profile(tuition, first_day, hint.cohort, ship)
    cohort = _pick(
        "cohort",
        "Year you entered UC",
        saved,
        hint.cohort,
        (profile[0], profile[3]) if profile else None,
        None,
    )
    residency = _pick(
        "residency",
        "Residency for tuition",
        saved,
        hint.nonresident,
        (profile[1], profile[3]) if profile else None,
        None,
        {True: "Nonresident", False: "California resident"},
    )
    learned_insurance: tuple[bool, str] | None = None
    if ship_named:
        learned_insurance = (True, "a UC SHIP charge is recorded")
    elif profile and not profile[2]:
        learned_insurance = (False, "your tuition and fees don't include UC SHIP")
    elif profile:
        learned_insurance = (True, "your tuition and fees are high enough to include UC SHIP")
    elif own_plan:
        latest = max(day_of(row) for row in own_plan)
        learned_insurance = (False, f"you bought your own plan on {latest:%b} {latest.day}")
    insurance = _pick(
        "insurance",
        "Health insurance",
        saved,
        hint.insurance,
        learned_insurance,
        True,
        {True: "UC SHIP", False: "Waived UC SHIP"},
    )
    coa = None
    if cohort.value is not None and residency.value is not None:
        coa = CoaProfile(cohort.value, residency.value, insurance.value, hint.total_cents)

    # ── Bills ─────────────────────────────────────────────────────────────
    found: list[Bill] = []
    if span:
        charged = {str(row["category"]) for row in spending if row["id"] in school_ids}
        for name, key, part, charges in (
            ("Tuition & fees", "school:tuition", "Tuition & fees", tuition),
            ("Campus housing", "school:room", "Housing", room),
        ):
            # Room charges from an earlier year end when the student moves out.
            if key == "school:room" and housing.value != "On-campus":
                continue
            school = school_bill(charges, span, as_of)
            if school:
                found.append(
                    Bill(
                        name=name,
                        amount_cents=school.amount,
                        categories=tuple(
                            sorted(charged & {str(row["category"]) for row in by_part[part]})
                        ),
                        cadence="Each quarter",
                        key=key,
                        why=school.why,
                        dates=school.dates,
                        grace=LEARNED_GRACE,
                    )
                )
    found.extend(_series_bill(item) for item in series if item.active)
    dismissed = tuple(bill for bill in found if bill.key in settings.dismissed)
    found = [bill for bill in found if bill.key not in settings.dismissed and bill.categories]

    pinned = [bill for bill in settings.bills if bill.pinned]
    found = [bill for bill in found if not any(_replaces(own, bill) for own in pinned)]
    learned_whole: set[str] = set()
    kept: list[Bill] = []
    for bill in found:
        if not bill.match and learned_whole & set(bill.categories):
            continue
        if not bill.match:
            learned_whole.update(bill.categories)
        kept.append(bill)
    covered = {category for bill in kept for category in bill.categories}
    earlier = [
        bill for bill in settings.bills if not bill.pinned and not covered & set(bill.categories)
    ]
    names: set[str] = set()
    bills = tuple(
        replace(bill, name=_unique(bill.name, names)) for bill in (*pinned, *earlier, *kept)
    )

    # ── How purchases count ───────────────────────────────────────────────
    pins = pinned_treatments(rules, fixed)
    whole = {category: bill for bill in bills if not bill.match for category in bill.categories}
    amounts: dict[str, list[int]] = defaultdict(list)
    for row in spending:
        if row["transaction_type"] == "expense":
            amounts[str(row["category"])].append(int(row["amount_cents"]))
    plain = [
        amount
        for category, values in amounts.items()
        if category not in whole and not says((*BILL_WORDS, *BIG_WORDS), category)
        for amount in values
    ]
    usual = median(plain) if plain else 0.0
    days = (as_of - first_day).days + 1
    answers: dict[str, CategoryAnswer] = {}
    for category in sorted({str(row["category"]) for row in rows} | set(pins) | set(whole)):
        if category in pins:
            treatment, why = pins[category], "you chose this"
        elif category in whole:
            treatment, why = "Commitments", f"paid as {whole[category].name}"
        elif says(BILL_WORDS, category):
            treatment, why = "Commitments", "its name says it's a bill"
        elif says(BIG_WORDS, category):
            treatment, why = "Irregular", "its name says it's an occasional cost"
        elif category in fixed:
            treatment, why = "Commitments", "a fixed category"
        elif lumpy(amounts[category], days, usual):
            treatment, why = "Irregular", "few purchases, and large ones"
        else:
            treatment, why = "Everyday", "day-to-day purchases"
        answers[category] = CategoryAnswer(
            treatment, category in pins, part_of(category), category in saved_parts, why
        )

    ordinary = [row for row in spending if answers[str(row["category"])].treatment == "Everyday"]
    big = big_purchase(ordinary, as_of)
    ignored = {bill.key for bill in dismissed}
    repeating = {
        identifier for item in series if _series_key(item) not in ignored for identifier in item.ids
    }
    exceptions: dict[str, dict[str, str]] = {}
    for row in spending:
        answer = answers[str(row["category"])]
        if answer.treatment != "Everyday" or answer.pinned:
            continue
        if row["id"] in repeating:
            exceptions[row["id"]] = {"treatment": "Commitments"}
        elif int(row["amount_cents"]) >= big and answer.part not in NEVER_BIG_PARTS:
            exceptions[row["id"]] = {"treatment": "Irregular"}
    effective_rules = {
        "categories": {category: answer.treatment for category, answer in answers.items()},
        "transactions": {**exceptions, **rules.get("transactions", {})},
        "parts": dict(saved_parts),
    }
    assert all(value in TREATMENTS for value in effective_rules["categories"].values())

    return AutoBudget(
        settings=replace(settings, housing=housing.value, bills=bills, coa=coa).validate(),
        rules=effective_rules,
        facts=(housing, cohort, residency, insurance),
        categories=answers,
        big_cents=big,
        habits=Habits(school_ids | repeating, moved_on),
        dismissed=dismissed,
    )


def settle(
    saved: BudgetSettings | None,
    auto: AutoBudget,
    *,
    choices: dict[str, Any],
    weekly_cents: int | None,
    total_cents: int | None,
    bills: tuple[Bill, ...],
    dismissed: Iterable[str],
) -> BudgetSettings:
    """Settings to save: the student's choices, with everything else left automatic.

    ``choices`` maps names from ``PINNABLE`` to a value, or ``None`` for automatic.
    """
    before = saved or BudgetSettings()
    old = before.coa or CoaProfile()
    answers: dict[str, Any] = {
        "housing": before.housing,
        "cohort": old.cohort,
        "residency": old.nonresident,
        "insurance": old.insurance,
    }
    blank: dict[str, Any] = {"housing": DEFAULT_HOUSING}
    for key in PINNABLE:
        if choices.get(key) is not None:
            answers[key] = choices[key]
        elif key in before.pinned:
            # A choice taken back is forgotten; an answer from earlier stays a fallback.
            answers[key] = blank.get(key)
    coa = CoaProfile(answers["cohort"], answers["residency"], answers["insurance"], total_cents)

    # Earlier bills the ledger now covers aren't shown, so saving must not lose them.
    shown = {bill.name for bill in auto.settings.bills if not bill.key}
    taken = {category for bill in bills for category in bill.categories}
    names = {bill.name for bill in bills}
    hidden = tuple(
        bill
        for bill in before.bills
        if not bill.pinned and bill.name not in shown | names and not taken & set(bill.categories)
    )
    return BudgetSettings(
        housing=answers["housing"],
        weekly_cents=weekly_cents,
        bills=(*bills, *hidden),
        coa=None if coa == CoaProfile() else coa,
        pinned=tuple(key for key in PINNABLE if choices.get(key) is not None),
        dismissed=tuple(dict.fromkeys(dismissed)),
    ).validate()
