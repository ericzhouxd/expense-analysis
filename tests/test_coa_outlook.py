"""The school year against UCLA's cost of attendance, with synthetic transactions only."""

from datetime import date, timedelta

import pytest
from ledgers import row

from expense_analysis.coa_outlook import arrival, coa_outlook, split_cents
from expense_analysis.patterns import SCHOOL_PARTS, Habits
from expense_analysis.spending_treatment import validate_rules
from expense_analysis.term_budget import (
    Bill,
    BudgetSettings,
    CoaProfile,
    school_year_dues,
    school_year_for,
    weekly_line,
)
from expense_analysis.university_presets import UCLA_2026, coa_components, ucla_benchmark

TODAY = date(2026, 11, 22)  # the Sunday that ends Fall 2026 week 8
START, END = date(2026, 9, 21), date(2027, 6, 13)
RESIDENT = CoaProfile("2025–26", nonresident=False)
RENT = Bill("Rent", 120000, ("Rent",), "Monthly", due_day=1)
TUITION = Bill("Tuition", 550000, ("Tuition",), "Each quarter")
EVERYDAY = {"categories": {"Food": "Everyday", "Flights": "Irregular"}}


def weekly_food(amount, first=date(2026, 6, 15), last=TODAY):
    """The same spending every Wednesday."""
    day = first + timedelta(days=2)
    rows = []
    while day <= last:
        rows.append(row(f"food{day}", day, amount))
        day += timedelta(days=7)
    return rows


def outlook(rows, *, bills=(RENT, TUITION), today=TODAY, rules=EVERYDAY, habits=None, **settings):
    settings.setdefault("coa", RESIDENT)
    return coa_outlook(BudgetSettings(bills=tuple(bills), **settings), rows, today, rules, habits)


def paid_so_far():
    return [
        row("tuition", "2026-09-10", 550000, "Tuition"),
        row("oct", "2026-09-30", 120000, "Rent"),
        row("nov", "2026-11-01", 120000, "Rent"),
    ]


def test_parts_sum_to_the_published_total_and_waiving_insurance_lowers_it():
    for housing in UCLA_2026["housing"]:
        for nonresident in (False, True):
            parts = coa_components("2026–27", housing, nonresident)
            assert sum(parts.values()) == sum(
                ucla_benchmark("2026–27", housing, nonresident).values()
            )
    full = sum(coa_components("2025–26", "Off-campus", False).values())
    waived = sum(coa_components("2025–26", "Off-campus", False, insurance=False).values())
    assert full - waived == UCLA_2026["insurance"]
    with pytest.raises(ValueError, match="entry year"):
        coa_components("1999–00", "Off-campus", False)


def test_there_is_no_verdict_without_a_profile_or_outside_the_published_year():
    missing = outlook([], coa=None)
    assert (missing["ready"], missing["reason"]) == (False, "profile")
    for day in (date(2026, 7, 1), date(2030, 1, 1)):
        other = outlook([], today=day)
        assert (other["ready"], other["reason"]) == (False, "year")


def test_layers_add_up_and_parts_explain_the_projection():
    result = outlook([*paid_so_far(), *weekly_food(20000)])
    assert result["projected"] == sum(result["layers"].values())
    assert sum(part["projected"] for part in result["parts"]) == result["projected"]
    assert result["margin"] == result["line"] - result["projected"]
    assert result["low"] <= result["projected"] <= result["high"]
    published = sum(part["published"] for part in result["parts"])
    assert published + result["adjustment"] == result["line"]
    assert all(type(value) is int for value in result["layers"].values())


def test_costs_count_for_the_year_they_pay_for():
    rows = [
        *paid_so_far(),
        *weekly_food(20000),
        row("september", "2026-09-01", 120000, "Rent"),  # mostly after classes begin
        row("august", "2026-08-01", 120000, "Rent"),
        row("last-year", "2026-04-01", 550000, "Tuition"),
        row("labelled", "2026-06-20", 90000, "Housing", "Deposit 26-27"),
        row("trip", "2026-08-01", 30000, "Flights"),  # the way back to campus
        row("vacation", "2026-06-25", 30000, "Flights"),
        row("card", "2026-10-05", 999999, "Food", kind="transfer"),
        row("aid", "2026-10-05", 999999, "Food", kind="income"),
        row("later", "2026-12-01", 999999),
    ]
    parts = {part["part"]: part for part in outlook(rows)["parts"]}
    assert parts["Tuition & fees"]["recorded"] == 550000  # paid before Week 0
    assert parts["Housing"]["recorded"] == 3 * 120000 + 90000
    # September through June, and the deposit that says which year it is for.
    assert parts["Housing"]["projected"] == 10 * 120000 + 90000
    assert parts["Transportation"]["recorded"] == 30000
    # Wednesdays from Week 0 through Week 8.
    assert parts["Food"]["recorded"] == 9 * 20000
    refunded = outlook([*rows, row("refund", "2026-10-06", 5000, kind="refund")])
    assert {p["part"]: p for p in refunded["parts"]}["Food"]["recorded"] == 9 * 20000 - 5000


@pytest.mark.parametrize(
    ("due_day", "count"),
    [(1, 10), (4, 10), (5, 9), (13, 9), (17, 9), (21, 9), (28, 9), (31, 9)],
)
def test_a_monthly_bill_counts_for_the_months_mostly_in_the_year(due_day, count):
    assert school_year_for(TODAY) == (START, END)
    dues = school_year_dues(Bill("Rent", 1, ("Rent",), due_day=due_day), (START, END))
    assert len(dues) == count
    assert dues == sorted(dues)
    # A lease that starts later has no earlier due dates.
    lease = Bill("Rent", 1, ("Rent",), due_day=due_day, since=date(2027, 1, 1))
    assert min(school_year_dues(lease, (START, END))) >= date(2027, 1, 1)


def test_a_due_date_before_the_year_is_only_owed_if_it_was_paid():
    paid = [row("sep", "2026-09-01", 120000, "Rent"), *paid_so_far()]
    for rows, count in ((paid, 7), (paid_so_far(), 7)):
        housing = outlook(rows)["layers"]["due"] - 2 * 550000
        assert housing == count * 120000


def test_moving_in_starts_the_year_a_little_early():
    def days(*numbers):
        return [START - timedelta(days=n) for n in numbers]

    assert arrival(days(6, 4, 1), START) == START - timedelta(days=6)
    assert arrival(days(40, 6, 4, 1), START) == START - timedelta(days=6)
    # Spending right through the summer says nothing about when they arrived.
    assert arrival(days(20, 17, 13, 9, 6, 4, 1), START) == START
    assert arrival([], START) == START
    move = [row(f"m{n}", START - timedelta(days=n), 5000) for n in (6, 4, 1)]
    food = weekly_food(20000, first=START)
    early = outlook([*food, *move])["layers"]["recorded"]
    assert early == outlook(food)["layers"]["recorded"] + 15000


def test_a_steady_spender_is_projected_and_safe_weekly_lands_on_the_line():
    year = weekly_food(20000, first=date(2025, 9, 22))
    result = outlook([*paid_so_far(), *year])
    weeks_left = (END - TODAY).days / 7
    assert result["layers"]["everyday"] == pytest.approx(20000 * weeks_left, rel=0.02)
    weekly = result["weekly"]
    assert weekly["typical"] == pytest.approx(20000, rel=0.02)
    landing = result["projected"] + (weekly["safe"] - weekly["typical"]) * weeks_left
    assert landing == pytest.approx(result["line"], abs=weeks_left)
    # What leaves room for surprises is never more than what lands on the line.
    assert weekly["sure"] <= weekly["safe"]
    # Earlier misses widen the range without moving the middle.
    wider = outlook([*paid_so_far(), *year], habits=Habits(spread=2.0))
    assert wider["projected"] == result["projected"]
    assert wider["high"] - wider["projected"] == pytest.approx(
        2 * (result["high"] - result["projected"]), abs=2
    )
    assert wider["weekly"]["sure"] <= weekly["sure"]


def test_charges_on_their_own_schedule_set_no_pace():
    food = weekly_food(20000, first=date(2025, 9, 22))
    old = [row(f"dorm{m}", f"2026-0{m}-10", 500000, "Housing") for m in (1, 3)]
    deposit = row("deposit", "2026-10-01", 20000, "Housing", "Deposit 26-27")
    ids = frozenset(r["id"] for r in old)
    plain = outlook([*paid_so_far(), *food])
    scheduled = outlook([*paid_so_far(), *food, *old], habits=Habits(scheduled=ids))
    assert scheduled["projected"] == plain["projected"]
    assert outlook([*paid_so_far(), *food, *old])["projected"] > plain["projected"]
    # A charge that names its school year is paid once, not every few months.
    once = outlook([*paid_so_far(), *food, deposit])
    assert once["projected"] == plain["projected"] + 20000


def test_a_move_means_only_the_weeks_since_set_the_pace():
    campus = weekly_food(5000, first=date(2025, 9, 22), last=date(2026, 9, 20))
    rows = [*paid_so_far(), *campus, *weekly_food(24000, first=START)]
    moved = outlook(rows, habits=Habits(moved_on=START))
    assert moved["weekly"]["typical"] == pytest.approx(24000, rel=0.05)
    assert moved["changed_on"] == START
    assert any("changed around Sep 21" in note for note in moved["notes"])


def test_the_verdict_follows_spending():
    cheap = outlook([*paid_so_far(), *weekly_food(10000)])
    assert cheap["verdict"] == "under" and cheap["margin"] > 0 and cheap["chance"] < 0.2
    dear = outlook([*paid_so_far(), *weekly_food(90000)])
    assert dear["verdict"] == "over" and dear["margin"] < 0 and dear["chance"] > 0.8
    swings = [
        row(f"s{i}", date(2026, 6, 17) + timedelta(weeks=i), 1000 + (i % 2) * 90000)
        for i in range(23)
    ]
    uneven = outlook([*paid_so_far(), *swings])
    assert uneven["high"] - uneven["low"] > cheap["high"] - cheap["low"]
    # An own total from MyUCLA moves the line and nothing else.
    own = outlook(
        [*paid_so_far(), *weekly_food(10000)],
        coa=CoaProfile("2025–26", False, total_cents=cheap["projected"] - 1),
    )
    assert own["own_total"] and own["projected"] == cheap["projected"]
    assert own["verdict"] == "close" and own["margin"] == -1
    # What is already recorded and due can't be undone.
    spent = cheap["layers"]["recorded"] + cheap["layers"]["due"] + cheap["layers"]["assumed"]
    past = outlook(
        [*paid_so_far(), *weekly_food(10000)],
        coa=CoaProfile("2025–26", False, total_cents=spent - 1),
    )
    assert past["verdict"] == "over" and past["chance"] == 1.0


def test_charges_the_ledger_never_sees_are_neutral_not_free():
    result = outlook(weekly_food(20000), bills=())
    parts = {part["part"]: part for part in result["parts"]}
    for name in ("Tuition & fees", "Health insurance", "Housing"):
        assert parts[name]["recorded"] == 0
        assert parts[name]["projected"] == parts[name]["published"]
        assert parts[name]["assumed"] == parts[name]["published"]
    # Utilities alone don't pass for rent.
    power = [row(f"p{m}", f"2026-{m}-05", 6000, "Utilities") for m in (10, 11)]
    utilities = outlook([*weekly_food(20000), *power], bills=())
    housing = next(p for p in utilities["parts"] if p["part"] == "Housing")
    assert housing["projected"] == housing["published"]
    # Waived insurance is on neither side.
    waived = outlook(weekly_food(20000), coa=CoaProfile("2025–26", False, insurance=False))
    insurance = next(p for p in waived["parts"] if p["part"] == "Health insurance")
    assert insurance["projected"] == insurance["published"] == 0


def test_one_bruinbill_payment_for_everything_is_not_counted_twice():
    charges = sum(coa_components("2025–26", "Off-campus", False)[p] for p in SCHOOL_PARTS)
    bill = Bill("BruinBill", charges // 3, ("Tuition",), "Each quarter")
    result = outlook(weekly_food(20000), bills=(RENT, bill))
    school = [p for p in result["parts"] if p["part"] in SCHOOL_PARTS]
    assert sum(p["projected"] for p in school) == pytest.approx(charges, abs=3)
    assert result["layers"]["assumed"] <= 3
    # With the dorm on it too, the room isn't assumed on top.
    room = coa_components("2025–26", "On-campus", False)["Housing"]
    everything = Bill("BruinBill", (charges + room) // 3, ("Tuition",), "Each quarter")
    dorm = outlook(weekly_food(20000), bills=(everything,), housing="On-campus")
    food = coa_components("2025–26", "On-campus", False)["Food"]
    recorded_food = 9 * 20000 + dorm["layers"]["everyday"]
    assert dorm["layers"]["assumed"] == pytest.approx(max(0, food - recorded_food), abs=3)


def test_on_campus_housing_and_meals_are_compared_together():
    result = outlook(weekly_food(5000), bills=(), housing="On-campus")
    both = next(p for p in result["parts"] if p["part"] == "Housing & food")
    assert "Food" not in {p["part"] for p in result["parts"]}
    assert both["projected"] == both["published"]
    assert sum(p["projected"] for p in result["parts"]) == result["projected"]


def test_days_without_records_are_estimated_instead_of_counted_as_free():
    year = date(2025, 9, 22)
    current = outlook([*paid_so_far(), *weekly_food(20000, first=year)])
    stale = outlook([*paid_so_far(), *weekly_food(20000, first=year, last=date(2026, 11, 4))])
    assert stale["through"] == date(2026, 11, 4)
    assert stale["projected"] == pytest.approx(current["projected"], rel=0.005)
    assert any("last entry is Nov 4" in note for note in stale["notes"])
    late_start = outlook(weekly_food(20000, first=date(2026, 10, 12)), bills=())
    from_start = outlook(weekly_food(20000), bills=())
    # Six weeks of history lean a little more on UCLA's own figures than twenty-three.
    assert late_start["projected"] == pytest.approx(from_start["projected"], rel=0.04)
    assert any("nothing recorded" in note for note in late_start["notes"])


def test_an_empty_ledger_is_predictable():
    result = outlook([], bills=())
    line = result["line"]
    assert result["layers"]["recorded"] == 0 and result["layers"]["one_offs"] == 0
    # Everything at UCLA's own figures, except books nobody has bought yet.
    assert 0 < line - result["projected"] < 200000
    assert result["chance"] > 0
    assert result["history_weeks"] == 0


def test_one_offs_lean_on_the_schools_figure_until_half_a_year_is_recorded():
    flight = row("flight", "2026-10-01", 60000, "Flights")
    short = outlook([*paid_so_far(), *weekly_food(20000, first=START), flight])
    published = next(p for p in short["parts"] if p["part"] == "Transportation")["published"]
    assert 0 < short["layers"]["one_offs"] < 2 * published
    assert any("half a year" in note for note in short["notes"])
    long = outlook([*paid_so_far(), *weekly_food(20000, first=date(2025, 9, 22)), flight])
    assert 0 < long["layers"]["one_offs"] < 60000
    assert not any("half a year" in note for note in long["notes"])
    # The same months of an earlier year count alongside the overall pace.
    spring = row("spring", "2026-03-01", 90000, "Flights")
    seen = outlook([*paid_so_far(), *weekly_food(20000, first=date(2025, 9, 22)), flight, spring])
    assert seen["layers"]["one_offs"] > 45000
    # It is recorded either way, and never inflates the weekly pace.
    for result in (short, long):
        transport = next(p for p in result["parts"] if p["part"] == "Transportation")
        assert transport["recorded"] == 60000
    assert long["weekly"]["typical"] == pytest.approx(20000, rel=0.02)


def test_a_closed_partial_payment_is_the_whole_bill_and_a_missing_one_is_still_owed():
    power = Bill("Power", 6000, ("Utilities",), "Monthly", due_day=5)
    paid = [row("oct", "2026-10-05", 3000, "Utilities")]
    result = outlook([*weekly_food(20000), *paid], bills=(RENT, power))
    # October settled at $30; November through May still expect $60 each. Nothing
    # was paid in September, so nothing was owed, and June is mostly after finals.
    # Two rents are long overdue and still owed.
    owed = result["layers"]["due"] - 9 * 120000
    assert owed == 7 * 6000
    # A guess that never came true lapses instead of staying owed.
    guess = Bill("Power", 6000, ("Utilities",), "Monthly", due_day=5, key="Monthly|power|x")
    lapsed = outlook(weekly_food(20000), bills=(RENT, guess))
    assert lapsed["layers"]["due"] - 9 * 120000 == 6 * 6000


def test_a_finished_year_is_judged_on_what_was_spent():
    rows = [*paid_so_far(), *weekly_food(20000, last=END)]
    result = outlook(rows, today=date(2027, 6, 14))
    assert result["complete"] is True and result["weekly"] is None
    assert result["layers"]["everyday"] == 0
    assert result["chance"] in (0.0, 1.0)


def test_a_dorm_meal_plan_is_not_counted_as_groceries_too():
    room = row("room", "2026-09-15", 600000, "Campus Housing")
    few = weekly_food(1000, first=START, last=date(2026, 10, 11))
    dorm = outlook([room, *few], bills=(), housing="On-campus", today=date(2026, 10, 11))
    flat = outlook(few, bills=(), today=date(2026, 10, 11))
    school = weekly_line(BudgetSettings(housing="On-campus"))["school_weekly"]
    # With almost no history both lean on UCLA's figure; the dorm one leaves food out.
    assert dorm["weekly"]["typical"] < school / 2 < flat["weekly"]["typical"]


def test_a_corrected_part_is_neither_projected_forward_nor_counted_twice():
    with pytest.raises(ValueError, match="cost of attendance"):
        validate_rules({"parts": {"Food": "Yachts"}})
    rows = [*weekly_food(20000), row("bruin", "2026-10-02", 400000, "BruinBill")]
    rules = {**EVERYDAY, "parts": {"BruinBill": "Tuition & fees"}}
    fixed = outlook(rows, bills=(RENT,), rules=rules)
    tuition = next(p for p in fixed["parts"] if p["part"] == "Tuition & fees")
    assert tuition["recorded"] == 400000
    assert tuition["projected"] == tuition["published"]
    assert fixed["weekly"]["typical"] == outlook(weekly_food(20000))["weekly"]["typical"]


def test_split_cents_is_exact():
    assert split_cents(100, {"A": 1, "B": 1, "C": 1}) == {"A": 34, "B": 33, "C": 33}
    assert sum(split_cents(99999, {"A": 7, "B": 0, "C": -5, "D": 3}).values()) == 99999
    assert split_cents(0, {}) == {} and split_cents(5, {}) == {"Personal": 5}


def test_profile_validates_round_trips_and_survives_a_legacy_plan():
    with pytest.raises(ValueError, match="entered UC"):
        CoaProfile("1999–00", False).validate()
    with pytest.raises(ValueError, match="more than"):
        CoaProfile("2025–26", False, total_cents=0).validate()
    settings = BudgetSettings(coa=CoaProfile("2024–25", True, False, 5000000), bills=(RENT,))
    assert BudgetSettings.from_dict(settings.to_dict()) == settings
    assert settings.rename_category("Rent", "Housing").coa == settings.coa
    older = settings.to_dict()
    del older["coa"]
    assert BudgetSettings.from_dict(older).coa is None
    legacy = {
        "schema_version": 2,
        "start": "2026-10-01",
        "reference": {"housing": "Commuter", "cohort": "2024–25", "residency": "Nonresident"},
    }
    assert BudgetSettings.from_dict(legacy).coa == CoaProfile("2024–25", True)
