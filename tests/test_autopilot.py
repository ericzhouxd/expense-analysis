"""Settings worked out from a made-up student's ledger, and what overrules them."""

from dataclasses import replace
from datetime import date

import pytest
from ledgers import monthly, row, student, weekly

from expense_analysis.autopilot import legacy_suggestion, pinned_treatments, resolve, settle
from expense_analysis.coa_outlook import coa_outlook
from expense_analysis.spending_treatment import classify_spending
from expense_analysis.term_budget import Bill, BudgetSettings, CoaProfile, next_due, term_budget

TODAY = date(2026, 11, 22)
NONE = {"housing": None, "cohort": None, "residency": None, "insurance": None}


def facts(auto):
    return {fact.key: (fact.value, fact.source) for fact in auto.facts}


def bills(auto):
    return {bill.name: bill for bill in auto.settings.bills}


def keep(saved, auto, **change):
    values = {
        "choices": NONE,
        "weekly_cents": None,
        "total_cents": None,
        "bills": tuple(bill for bill in auto.settings.bills if not bill.key),
        "dismissed": saved.dismissed if saved else (),
    }
    return settle(saved, auto, **{**values, **change})


def test_a_ledger_alone_is_enough():
    auto = resolve(None, None, student(), TODAY)
    assert facts(auto) == {
        "housing": ("Off-campus", "learned"),
        "cohort": ("2025–26", "learned"),
        "residency": (True, "learned"),
        "insurance": (False, "learned"),
    }
    assert auto.settings.coa == CoaProfile("2025–26", True, False)
    found = bills(auto)
    assert set(found) == {
        "Tuition & fees",
        "Rent",
        "Streaming service",
        "Student health plan 26-27",
    }
    assert found["Rent"].amount_cents == 900_00 and not found["Rent"].match
    # A subscription inside a category that holds other things is matched by name.
    assert found["Streaming service"].match and found["Streaming service"].due_day == 8
    # Last year's dorm is over.
    assert "Campus housing" not in found
    assert all(bill.key and bill.why for bill in auto.settings.bills)
    outlook = coa_outlook(auto.settings, student(), TODAY, auto.rules, auto.habits)
    assert outlook["ready"] and outlook["layers"]["assumed"] == 0
    tuition = next(p for p in outlook["parts"] if p["part"] == "Tuition & fees")
    assert tuition["projected"] == 3 * 17_850_00


@pytest.mark.parametrize("cents", [350_00, 900_00, 1_050_00, 2_400_00])
def test_rent_of_any_size_is_a_monthly_bill_through_june(cents):
    rows = [r for r in student() if r["category"] != "Rent"]
    rows += monthly(cents, ["2026-09", "2026-10", "2026-11"], 1, "Rent", "Landlord")
    auto = resolve(None, None, rows, TODAY)
    assert facts(auto)["housing"] == ("Off-campus", "learned")
    assert bills(auto)["Rent"].amount_cents == cents
    outlook = coa_outlook(auto.settings, rows, TODAY, auto.rules, auto.habits)
    housing = next(p for p in outlook["parts"] if p["part"] == "Housing")
    assert housing["projected"] == 10 * cents


def test_every_category_and_purchase_counts_by_itself():
    auto = resolve(None, None, student(), TODAY)
    treatments = {name: answer.treatment for name, answer in auto.categories.items()}
    assert treatments["Groceries"] == treatments["Dining Out"] == "Everyday"
    assert treatments["Rent"] == treatments["Tuition"] == "Commitments"
    assert treatments["Campus Housing"] == treatments["Insurance"] == "Commitments"
    assert treatments["Flight"] == "Irregular"
    assert not any(answer.pinned for answer in auto.categories.values())
    rows = {r["id"]: r for r in classify_spending(student(), auto.settings, auto.rules)}
    assert rows["monitor"]["spending_treatment"] == "Irregular"
    assert rows["Streaming service2026-11"]["spending_treatment"] == "Commitments"
    # Food is never big stuff, however large the shop.
    feast = row("feast", "2026-11-20", 400_00, "Groceries", "Party")
    auto = resolve(None, None, [*student(), feast], TODAY)
    again = {r["id"]: r for r in classify_spending([feast], auto.settings, auto.rules)}
    assert again["feast"]["spending_treatment"] == "Everyday"


def test_an_empty_ledger_has_predictable_defaults():
    auto = resolve(None, None, [], TODAY)
    assert facts(auto) == {
        "housing": ("Off-campus", "default"),
        "cohort": (None, "default"),
        "residency": (None, "default"),
        "insurance": (True, "default"),
    }
    assert auto.settings.bills == () and auto.categories == {} and auto.settings.coa is None
    # Far outside the published calendar is no different.
    assert resolve(None, None, [], date(2040, 1, 1)).settings.bills == ()


def test_choices_win_evidence_beats_old_answers_and_old_answers_beat_defaults():
    old = BudgetSettings(housing="On-campus", coa=CoaProfile("2024–25", False, True))
    learned = resolve(old, None, student(), TODAY)
    assert facts(learned)["housing"] == ("Off-campus", "learned")
    assert facts(learned)["residency"] == (True, "learned")
    # UC SHIP for an earlier entry year costs almost the same: an old answer decides.
    no_plan = [r for r in student() if r["category"] != "Insurance"]
    assert facts(resolve(old, None, no_plan, TODAY))["cohort"] == ("2024–25", "learned")
    assert facts(resolve(None, None, no_plan, TODAY))["cohort"] == ("2025–26", "learned")
    quiet = resolve(old, None, weekly(50_00, date(2026, 9, 21), TODAY), TODAY)
    assert facts(quiet)["housing"] == ("On-campus", "earlier")
    assert facts(quiet)["cohort"] == ("2024–25", "earlier")
    pinned = replace(old, pinned=("housing", "residency"))
    auto = resolve(pinned, None, student(), TODAY)
    assert facts(auto)["housing"] == ("On-campus", "yours")
    assert facts(auto)["residency"] == (False, "yours")
    housing = auto.facts[0]
    assert housing.auto_text == "Off-campus" and "rent" in housing.auto_why


def test_bills_the_student_entered_replace_the_same_learned_ones():
    own = Bill("My rent", 950_00, ("Rent",), due_day=3, pinned=True)
    saved = BudgetSettings(bills=(own,), pinned=("housing",))
    found = bills(resolve(saved, None, student(), TODAY))
    assert "Rent" not in found and found["My rent"] == own
    # One entered before anything was automatic yields to the ledger...
    earlier = replace(own, pinned=False)
    assert "My rent" not in bills(resolve(BudgetSettings(bills=(earlier,)), None, student(), TODAY))
    # ...and stays where the ledger has nothing.
    gym = Bill("Gym", 30_00, ("Gym",))
    assert "Gym" in bills(resolve(BudgetSettings(bills=(gym,)), None, student(), TODAY))
    # Matched by name, an own bill leaves the rest of its category alone.
    named = Bill(
        "Streaming",
        12_99,
        ("Entertainment",),
        pinned=True,
        match=frozenset({"streaming", "service"}),
    )
    saved = BudgetSettings(bills=(named,))
    auto = resolve(saved, None, student(), TODAY)
    assert "Streaming service" not in bills(auto) and "Streaming" in bills(auto)
    assert auto.categories["Entertainment"].treatment == "Everyday"
    kept = {r["id"]: r for r in classify_spending(student(), auto.settings, auto.rules)}
    assert kept["Streaming service2026-11"]["spending_treatment"] == "Commitments"
    assert BudgetSettings.from_dict(saved.to_dict()) == saved


def test_a_dismissed_bill_stays_away_and_can_come_back():
    auto = resolve(None, None, student(), TODAY)
    key = bills(auto)["Streaming service"].key
    saved = BudgetSettings(dismissed=(key,))
    without = resolve(saved, None, student(), TODAY)
    assert "Streaming service" not in bills(without)
    assert [bill.name for bill in without.dismissed] == ["Streaming service"]
    rows = {r["id"]: r for r in classify_spending(student(), without.settings, without.rules)}
    assert rows["Streaming service2026-11"]["spending_treatment"] == "Everyday"
    # Renaming the category must not bring it back.
    renamed = saved.rename_category("Entertainment", "Fun")
    moved = [{**r, "category": "Fun"} if r["category"] == "Entertainment" else r for r in student()]
    assert "Streaming service" not in bills(resolve(renamed, None, moved, TODAY))


def test_saving_one_choice_leaves_everything_else_automatic():
    auto = resolve(None, None, student(), TODAY)
    saved = keep(None, auto, choices={**NONE, "housing": "On-campus"})
    assert saved.pinned == ("housing",) and saved.housing == "On-campus"
    assert saved.coa is None and saved.bills == ()
    assert facts(resolve(saved, None, student(), TODAY))["cohort"] == ("2025–26", "learned")
    # Taken back, the choice is forgotten.
    back = keep(saved, resolve(saved, None, student(), TODAY))
    assert back.pinned == () and back.housing == "Off-campus"
    # Answers from before anything was automatic survive as fallbacks.
    rent = Bill("Old rent", 700_00, ("Rent",))
    old = BudgetSettings(housing="On-campus", bills=(rent,), coa=CoaProfile("2024–25", True, False))
    kept = keep(old, resolve(old, None, student(), TODAY), weekly_cents=250_00)
    assert kept.housing == "On-campus" and kept.coa == old.coa and kept.weekly_cents == 250_00
    # The ledger covers the old rent, so it isn't shown, but saving doesn't lose it.
    assert kept.bills == (rent,)
    replaced = keep(
        old,
        resolve(old, None, student(), TODAY),
        bills=(Bill("Rent", 950_00, ("Rent",), pinned=True),),
    )
    assert [bill.name for bill in replaced.bills] == ["Rent"]
    with pytest.raises(ValueError, match="entered UC"):
        keep(None, auto, choices={**NONE, "cohort": "1999–00"})


def test_only_real_choices_survive_from_the_old_category_table():
    fixed = ("Rent",)
    rules = {"categories": {"Rent": "Commitments", "Flight": "Irregular", "Food": "Everyday"}}
    assert pinned_treatments(rules, fixed) == {}
    rules["categories"] |= {"Food": "Irregular", "Gym": "Commitments"}
    assert pinned_treatments(rules, fixed) == {"Food": "Irregular", "Gym": "Commitments"}
    assert pinned_treatments({**rules, "auto": True}, fixed) == rules["categories"]
    assert legacy_suggestion("Travel", fixed) == "Irregular"
    auto = resolve(None, rules, student(), TODAY, fixed)
    assert auto.categories["Gym"].pinned and auto.categories["Gym"].treatment == "Commitments"
    # A choice for a category is never overruled purchase by purchase.
    chosen = resolve(None, {"categories": {"Tech": "Everyday"}, "auto": True}, student(), TODAY)
    assert "monitor" not in chosen.rules["transactions"]
    marked = {"transactions": {"monitor": {"treatment": "Everyday"}}}
    assert resolve(None, marked, student(), TODAY).rules["transactions"]["monitor"] == {
        "treatment": "Everyday"
    }


def test_learned_bills_are_tracked_like_any_other():
    auto = resolve(None, None, student(), TODAY)
    budget = term_budget(auto.settings, student(), TODAY, auto.rules)
    dues = {(b["name"], b["due"].isoformat()): b for b in budget["bills"]}
    assert dues["Rent", "2026-11-01"]["status"] == "paid"
    assert dues["Rent", "2026-12-01"]["status"] == "upcoming"
    assert dues["Rent", "2026-12-01"]["learned"]
    assert next_due(bills(auto)["Rent"], student(), TODAY) == date(2026, 12, 1)
    assert next_due(bills(auto)["Tuition & fees"], student(), TODAY) == date(2026, 12, 18)
    assert next_due(Bill("Once", 1, (), "Once", due=date(2026, 1, 1)), [], TODAY) is None
    # A guessed date gets a few days before a payment counts as missing.
    unpaid = [r for r in student() if r["id"] != "Rent to landlord2026-11"]
    auto = resolve(None, None, unpaid, date(2026, 11, 6))
    late = term_budget(auto.settings, unpaid, date(2026, 11, 6), auto.rules)["bills"]
    assert {b["status"] for b in late if b["due"] == date(2026, 11, 1)} == {"soon"}
    late = term_budget(auto.settings, unpaid, date(2026, 11, 12), auto.rules)["bills"]
    assert {b["status"] for b in late if b["due"] == date(2026, 11, 1)} == {"late"}


def test_an_unrecognized_charge_leaves_the_profile_open():
    rows = [
        row("t", "2026-09-10", 9_000_00, "Tuition"),
        *monthly(90_00, ["2026-10"], 1, "Rent", "x"),
    ]
    auto = resolve(None, None, rows, TODAY)
    assert facts(auto)["cohort"] == (None, "default")
    ship = [*rows, row("s", "2026-09-12", 1_000_00, "Tuition", "UC SHIP fall")]
    assert facts(resolve(None, None, ship, TODAY))["insurance"] == (True, "learned")
    plan = [*rows, row("i", "2026-08-12", 800_00, "Insurance", "Private plan")]
    assert facts(resolve(None, None, plan, TODAY))["insurance"] == (False, "learned")
