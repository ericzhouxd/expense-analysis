"""The budget as it stood earlier, rebuilt from a made-up ledger."""

from datetime import date, timedelta

from ledgers import row, student

from expense_analysis import replay
from expense_analysis.replay import LINE_FLOOR, smart_budget
from expense_analysis.term_budget import BudgetSettings, CoaProfile, term_budget, weekly_line

TODAY = date(2026, 11, 22)
START = date(2026, 9, 21)
TIGHT = BudgetSettings(coa=CoaProfile(total_cents=75_000_00))


def test_the_projection_is_checked_against_the_finished_year():
    smart = smart_budget(None, None, student(), TODAY)
    (record,) = smart.record
    assert record["label"] == "2025–26"
    assert record["miss"] == record["projected"] - record["actual"]
    # Everything that year paid for, including what was paid before it began.
    assert 3 * 17_850_00 + 3 * 6_000_00 < record["actual"] < 80_000_00
    assert record["percent"] < 15
    assert smart.auto.habits.spread >= 1.0
    # No earlier year, nothing to check against.
    recent = [r for r in student() if r["transaction_date"] >= "2026-08-01"]
    assert smart_budget(None, None, recent, TODAY).record == []
    empty = smart_budget(None, None, [], TODAY)
    assert empty.record == [] and empty.lines == {}


def test_the_line_only_tightens_when_the_year_is_heading_over():
    roomy = smart_budget(None, None, student(), TODAY)
    school = weekly_line(roomy.auto.settings)["school_weekly"]
    budget = term_budget(roomy.auto.settings, student(), TODAY, roomy.auto.rules, lines=roomy.lines)
    assert budget["line"]["source"] == "school" and budget["line"]["weekly"] == school
    tight = smart_budget(TIGHT, None, student(), TODAY)
    assert set(tight.lines) == {START + timedelta(weeks=i) for i in range(9)}
    budget = term_budget(tight.auto.settings, student(), TODAY, tight.auto.rules, lines=tight.lines)
    assert budget["line"]["source"] == "coa"
    assert school * LINE_FLOOR - 100 < budget["line"]["weekly"] < school
    # Weeks ahead use this week's line, and each finished week the one it had.
    by_start = {week["start"]: week["line"] for week in budget["weeks"]}
    assert by_start[date(2026, 12, 7)] == budget["line"]["weekly"]
    assert budget["totals"]["line_to_date"] == sum(
        week["line"] for week in budget["weeks"] if week["state"] == "past"
    )
    # An amount of the student's own is never touched.
    own = smart_budget(BudgetSettings(weekly_cents=333_00), None, student(), TODAY)
    assert own.lines == {}


def test_what_happens_later_never_changes_an_earlier_week():
    before = smart_budget(TIGHT, None, student(), TODAY).lines
    trip = row("trip", "2026-11-12", 2_500_00, "Flight", "Trip")
    after = smart_budget(TIGHT, None, [*student(), trip], TODAY).lines
    for week, amount in before.items():
        if week <= date(2026, 11, 9):
            assert after[week] == amount
    assert after[date(2026, 11, 16)] < before[date(2026, 11, 16)]


def test_past_weeks_are_worked_out_once_and_again_after_an_edit(monkeypatch):
    replay._cache.clear()
    calls = []
    original = replay.coa_outlook

    def counting(*args, **kwargs):
        calls.append(args[2])
        return original(*args, **kwargs)

    monkeypatch.setattr(replay, "coa_outlook", counting)
    rows = student()
    smart_budget(TIGHT, None, rows, TODAY)
    first = len(calls)
    smart_budget(TIGHT, None, [dict(r) for r in rows], TODAY)
    assert len(calls) == first == 9
    edited = [
        {**r, "amount_cents": r["amount_cents"] + 1} if r["id"].startswith("market2026-11") else r
        for r in rows
    ]
    smart_budget(TIGHT, None, edited, TODAY)
    # Only the Mondays after the edited purchases had to be done again.
    assert calls[first:] and min(calls[first:]) >= date(2026, 11, 8)
    # The cache never grows without bound.
    monkeypatch.setattr(replay, "_CACHE_SIZE", 5)
    smart_budget(None, {"parts": {"Tech": "Books"}}, rows, TODAY)
    assert len(replay._cache) <= 5
