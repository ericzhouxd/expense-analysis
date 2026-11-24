"""Learning categories from made-up entries."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from expense_analysis.category_learning import CategoryHistory, words_of

TODAY = date(2026, 11, 9)
CATEGORIES = ("Food", "Dining Out", "Tech", "Income", "Uncategorized")


def entry(
    number: int,
    description: str,
    category: str,
    *,
    days: int = 10,
    merchant: str = "",
    kind: str = "expense",
) -> dict[str, Any]:
    day = TODAY - timedelta(days=days)
    return {
        "id": str(number),
        "transaction_date": day.isoformat(),
        "created_at": f"{day} 12:00:00",
        "description": description,
        "merchant": merchant,
        "category": category,
        "transaction_type": kind,
    }


def history(rows: list[dict[str, Any]], corrections: dict[str, str] | None = None):
    return CategoryHistory(rows, corrections or {}, CATEGORIES, TODAY)


def test_the_same_name_is_enough_and_dates_do_not_matter():
    found = history([entry(1, "Ramen night", "Dining Out")]).suggest("ramen night 11/4")
    assert found is not None
    assert (found.category, found.source, found.share) == ("Dining Out", "name", 1.0)
    assert [(e.text, e.category, e.count) for e in found.evidence] == [
        ("ramen night 11/4", "Dining Out", 1)
    ]


def test_words_carry_over_to_a_new_name_with_the_reason():
    rows = [
        entry(1, "Ramen with friends", "Dining Out"),
        entry(2, "Spicy ramen", "Dining Out"),
        entry(3, "Weekly groceries", "Food"),
    ]
    found = history(rows).suggest("Ramen downtown")
    assert found is not None
    assert (found.category, found.source) == ("Dining Out", "words")
    assert [(e.text, e.count) for e in found.evidence] == [("ramen", 2)]
    # Plurals are one word, and a word never seen says nothing.
    assert history(rows).category_for("Grocery run") == "Food"
    assert history(rows).suggest("Zzz") is None
    assert history([]).suggest("Ramen") is None


def test_a_word_used_for_everything_decides_nothing():
    rows = [
        entry(1, "Campus lunch", "Dining Out"),
        entry(2, "Campus snacks", "Food"),
        entry(3, "Campus cable", "Tech"),
    ]
    assert history(rows).suggest("Campus thing") is None


def test_recent_entries_outweigh_old_ones():
    old = [entry(n, "Protein bars", "Food", days=900) for n in range(3)]
    new = [entry(10 + n, "Protein bars", "Dining Out", days=5) for n in range(2)]
    assert history(old + new).category_for("Protein bars") == "Dining Out"


def test_one_correction_turns_around_a_habit_and_its_words():
    rows = [entry(n, "Boba", "Food", days=20 + n) for n in range(8)]
    assert history(rows).category_for("Boba") == "Food"
    rows.append(entry(99, "Boba", "Dining Out", days=2))
    # Without saying it was a correction, one entry is one entry.
    assert history(rows).category_for("Boba") == "Food"
    corrected = {"99": "2026-11-08 09:00:00"}
    assert history(rows, corrected).category_for("Boba") == "Dining Out"
    assert history(rows, corrected).category_for("Boba tea") == "Dining Out"
    # What is recorded afterwards counts in full again.
    rows += [entry(100 + n, "Boba", "Food", days=0) for n in range(6)]
    assert history(rows, corrected).category_for("Boba") == "Food"


def test_correcting_back_undoes_a_correction():
    rows = [
        entry(1, "Boba", "Food", days=30),
        entry(2, "Boba", "Dining Out", days=20),
        entry(3, "Boba", "Food", days=10),
    ]
    corrected = {"2": "2026-10-21 09:00:00", "3": "2026-11-01 09:00:00"}
    assert history(rows, corrected).category_for("Boba") == "Food"


def test_an_old_entry_corrected_today_counts_as_today():
    rows = [entry(1, "Club fee", "Tech", days=800), entry(2, "Club fee", "Food", days=700)]
    corrected = {"1": "2026-11-09 08:00:00"}
    assert history(rows, corrected).category_for("Club fee") == "Tech"


def test_types_do_not_teach_each_other_except_refunds():
    rows = [entry(1, "Monitor stand", "Tech"), entry(2, "Paycheck", "Income", kind="income")]
    assert history(rows).category_for("Monitor stand", transaction_type="refund") == "Tech"
    assert history(rows).category_for("Monitor stand", transaction_type="income") is None
    assert history(rows).category_for("Paycheck") is None
    assert history(rows).category_for("Paycheck", transaction_type="income") == "Income"


def test_a_merchant_needs_two_entries_that_agree():
    rows = [entry(1, "Towels", "Food", merchant="Corner Mart")]
    assert history(rows).suggest("Zzz", "corner mart") is None
    rows.append(entry(2, "Sponges", "Food", merchant="Corner Mart"))
    found = history(rows).suggest("Zzz", "corner mart")
    assert found is not None and (found.category, found.source) == ("Food", "merchant")
    rows.append(entry(3, "Charger", "Tech", merchant="Corner Mart"))
    assert history(rows).suggest("Zzz", "corner mart") is None


def test_unknown_and_missing_categories_teach_nothing():
    rows = [entry(1, "Ramen", "Uncategorized"), entry(2, "Ramen", "Deleted category")]
    assert history(rows).suggest("Ramen") is None
    assert history([entry(1, "123", "Food")]).category_for("123") == "Food"
    assert history([entry(1, "Ramen", "Food")]).suggest("  ") is None


def test_unspaced_scripts_are_compared_by_pairs():
    assert set(words_of("牛肉麵")) == {"牛肉", "肉麵"}
    rows = [entry(1, "牛肉麵", "Dining Out"), entry(2, "牛肉麵大碗", "Dining Out")]
    assert history(rows).category_for("紅燒牛肉麵") == "Dining Out"
