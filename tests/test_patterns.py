"""Finding repeating charges, school charges and housing in made-up ledgers."""

from datetime import date, timedelta

import pytest
from ledgers import monthly, row, student

from expense_analysis.patterns import (
    BIG_CEILING,
    BIG_FLOOR,
    big_purchase,
    circular_day,
    coa_part,
    housing_in,
    labelled_year,
    lumpy,
    quarter_charges,
    rent_payments,
    repeating_charges,
    school_bill,
)
from expense_analysis.term_budget import school_year_for, school_years_back_to

TODAY = date(2026, 11, 22)
SPAN = school_year_for(TODAY) or (TODAY, TODAY)
SPANS = school_years_back_to(SPAN, date(2025, 8, 1))
MONTHS = [f"2026-{month:02d}" for month in range(5, 12)]


def found(rows, as_of=TODAY):
    return {item.name: item for item in repeating_charges(rows, as_of, frozenset())}


def test_a_school_year_in_a_description_is_read_only_when_it_makes_sense():
    assert labelled_year(row("a", "2026-07-01", 1, description="Plan 26-27")) == 2026
    assert labelled_year(row("a", "2026-07-01", 1, description="Plan 2026–2027")) == 2026
    assert labelled_year(row("a", "2026-07-01", 1, description="Retreat 2/14-2/16")) is None
    assert labelled_year(row("a", "2026-07-01", 1, description="Sizes 10-11")) is None
    assert labelled_year(row("a", "2026-07-01", 1, description="")) is None


def test_quarter_charges_post_together_and_stray_fees_are_not_one():
    rows = [
        row("main", "2026-09-01", 500_000, "Tuition"),
        row("fee", "2026-09-03", 2_000, "Tuition"),
        row("back", "2026-09-04", 1_000, "Tuition", kind="refund"),
        row("late", "2026-10-15", 5_000, "Tuition"),
        row("winter", "2026-12-20", 480_000, "Tuition"),
        row("small", "2027-03-20", 30_000, "Tuition"),
    ]
    charges = quarter_charges(rows, [SPAN])
    assert {at: charge.total for (_, at), charge in charges.items()} == {0: 501_000, 1: 480_000}
    assert charges[SPAN, 0].ids == {"main", "fee", "back"}
    assert quarter_charges([], [SPAN]) == {}


def test_the_rest_of_the_year_is_expected_like_last_year():
    charges = quarter_charges([r for r in student() if r["category"] == "Tuition"], SPANS)
    bill = school_bill(charges, SPAN, TODAY)
    assert bill is not None
    assert bill.amount == 17_850_00 and bill.paid == 1
    assert bill.dates[-2:] == (date(2026, 12, 18), date(2027, 3, 10))
    # A quarter that went by unpaid means nobody is charging any more.
    rooms = quarter_charges([r for r in student() if r["category"] == "Campus Housing"], SPANS)
    assert school_bill(rooms, SPAN, TODAY) is None
    # Before it is due, last year's charge is still the best guess.
    assert school_bill(rooms, SPAN, date(2026, 9, 25)) is not None
    assert school_bill({}, SPAN, TODAY) is None


def test_subscriptions_are_found_and_habits_are_not():
    series = found(
        [
            *monthly(11_99, MONTHS, 8, "Entertainment", "Streaming"),
            *[
                row(f"c{i}", TODAY - timedelta(days=9 * i), 550, "Coffee", "Latte")
                for i in range(9)
            ],
            # The same shop about once a month, but never the same amount.
            *[
                row(f"s{m}", f"{m}-08", 4_000 + 900 * i, "Clothes", "Store")
                for i, m in enumerate(MONTHS)
            ],
        ]
    )
    assert set(series) == {"Streaming"}
    streaming = series["Streaming"]
    assert (streaming.cadence, streaming.amount, streaming.due_day) == ("Monthly", 11_99, 8)
    assert streaming.active and streaming.count == len(MONTHS)
    # Cancelled: still recognized, no longer expected.
    stopped = found(monthly(11_99, MONTHS[:4], 8, "Entertainment", "Streaming"))
    assert not stopped["Streaming"].active


def test_rent_needs_one_payment_and_a_prorated_first_month_is_not_the_rent():
    one = found([row("r", "2026-10-30", 80_000, "Rent", "October rent")], date(2026, 11, 10))
    assert one["Rent"].amount == 80_000 and one["Rent"].due_day == 1
    two = found(
        [
            row("r1", "2026-09-12", 30_000, "Rent", "September"),
            row("r2", "2026-10-01", 80_000, "Rent", "October"),
        ],
        date(2026, 10, 20),
    )
    # Too different to call monthly yet, but never the average of the two.
    assert two == {} or two["Rent"].amount == 80_000
    several = found(
        [
            row("r1", "2026-09-01", 72_000, "Rent", "September"),
            row("r2", "2026-10-01", 80_000, "Rent", "October"),
            row("r3", "2026-11-01", 80_000, "Rent", "November"),
        ]
    )
    assert several["Rent"].amount == 80_000 and several["Rent"].whole_category


def test_yearly_charges_and_prepaid_plans():
    series = found(
        [
            row("a", "2024-11-25", 20_000, "Entertainment", "Club retreat"),
            row("b", "2025-11-24", 21_000, "Entertainment", "Club retreat"),
            row("cheap1", "2025-01-10", 3_000, "Clothes", "Socks"),
            row("cheap2", "2026-01-12", 3_000, "Clothes", "Socks"),
            *monthly(1_500, ["2025-12", "2026-01", "2026-02"], 4, "Cell Phone", "Carrier"),
            row("plan", "2026-03-04", 18_000, "Cell Phone", "Carrier 1 Year"),
        ]
    )
    assert series["Club retreat"].next_due == date(2026, 11, 24)
    assert series["Club retreat"].active
    assert "Socks" not in series
    plan = series["Carrier 1 Year"]
    assert plan.next_due == date(2027, 3, 4) and plan.active
    # The monthly payments it replaced are over, and belong to no pace.
    assert {"Carrier2025-12", "Carrier2026-02", "plan"} <= plan.ids
    assert not any(s.active for s in series.values() if s.cadence == "Monthly")


def test_where_the_student_lives_follows_the_money():
    rows = student()
    housing = [r for r in rows if coa_part(r["category"]) == "Housing"]
    room = quarter_charges([r for r in rows if r["category"] == "Campus Housing"], SPANS)
    rent = rent_payments(housing, TODAY)
    assert len(rent) == 3
    now, before = housing_in(SPANS[0], room, rent, TODAY), housing_in(SPANS[1], room, rent, TODAY)
    assert now is not None and now[0] == "Off-campus" and "rent" in now[1]
    assert before is not None and before[0] == "On-campus"
    assert housing_in(SPANS[0], {}, [], TODAY) is None


def test_rent_is_never_taken_for_the_schools_room_charge():
    # As large as a room charge, and nothing in the name says rent.
    months = ["2026-09", "2026-10", "2026-11"]
    plain = monthly(1_800_00, months, 2, "Housing", "Westside Properties")
    assert {r["id"] for r in rent_payments(plain, TODAY)} == {r["id"] for r in plain}
    # A dorm on an installment plan and a large power bill are not rent.
    dorm = monthly(1_800_00, months, 2, "Campus Housing", "Hill installment")
    power = monthly(260_00, months, 9, "Utilities", "Power company")
    assert rent_payments([*dorm, *power], TODAY) == []
    assert rent_payments([], TODAY) == []


def test_big_purchases_scale_with_the_student_within_reason():
    def ledger(amount, count=30):
        return [row(f"p{i}", "2026-10-05", amount) for i in range(count)]

    assert big_purchase([], TODAY) == 10_000
    assert big_purchase(ledger(2_000, count=5), TODAY) == 10_000
    assert big_purchase(ledger(300), TODAY) == BIG_FLOOR
    assert big_purchase(ledger(2_000), TODAY) == 12_000
    assert big_purchase(ledger(90_000), TODAY) == BIG_CEILING
    assert lumpy([40_000, 55_000, 30_000], 300, 1_500)
    assert not lumpy([1_500] * 40, 300, 1_500)
    assert not lumpy([40_000], 300, 1_500) and not lumpy([1, 2, 3], 0, 0)


@pytest.mark.parametrize(
    ("days", "middle"), [([1, 1, 1], 1), ([30, 31, 2], 1), ([14, 15, 16], 15), ([28, 2, 30], 30)]
)
def test_the_middle_of_a_month_end_is_at_the_month_end(days, middle):
    assert abs(circular_day(days) - middle) <= 1


def test_category_parts_have_sensible_guesses_and_accept_corrections():
    expected = {
        "Tuition": "Tuition & fees",
        "School Fees": "Tuition & fees",
        "Insurance": "Health insurance",
        "Car Insurance": "Transportation",
        "Rent": "Housing",
        "Housing and Meal Plan": "Housing",
        "Internet": "Housing",
        "Dining Out": "Food",
        "Flight": "Transportation",
        "Stationery": "Books",
        "Entertainment": "Personal",
        "Uncategorized": "Personal",
    }
    assert {name: coa_part(name) for name in expected} == expected
    assert coa_part("BruinBill", {"BruinBill": "Tuition & fees"}) == "Tuition & fees"
