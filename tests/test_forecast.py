"""The forecaster learns from made-up weeks, so the right answer is known."""

from datetime import date, timedelta

import numpy as np
import pytest

from expense_analysis.forecast import (
    HALF_LIVES,
    everyday_rate,
    memory,
    one_off_rate,
    run_rate,
    stretch_start,
    stretches,
)
from expense_analysis.term_budget import learning_kind

KIND = learning_kind()
MONDAY = date(2025, 9, 22)


def weeks(count, first=MONDAY):
    return [first + timedelta(weeks=i) for i in range(count)]


def days(first, count):
    return [first + timedelta(days=i) for i in range(count)]


def always(_):
    return "quarter"


def test_a_flat_history_projects_itself():
    past = weeks(40)
    ahead = days(past[-1] + timedelta(weeks=1), 70)
    flat = dict.fromkeys(past, 10_000)
    assert run_rate(flat, past, ahead, 26.0).mean == pytest.approx(100_000)
    everyday = everyday_rate(flat, past, ahead, always, 10_000)
    assert everyday.mean == pytest.approx(100_000)
    assert everyday.since is None and everyday.weeks == 40
    assert everyday_rate(flat, past, [], always, 10_000).mean == 0
    assert run_rate({}, [], ahead, 26.0).mean == 0
    assert run_rate({}, past, ahead, 26.0).mean == 0


def test_the_schools_estimate_only_matters_before_there_is_history():
    ahead = days(MONDAY + timedelta(weeks=60), 70)
    short = everyday_rate(dict.fromkeys(weeks(4), 10_000), weeks(4), ahead, always, 30_000)
    long = everyday_rate(dict.fromkeys(weeks(52), 10_000), weeks(52), ahead, always, 30_000)
    assert 100_000 < long.mean < 110_000 < short.mean < 150_000
    nothing = everyday_rate({}, [], ahead, always, 30_000)
    assert nothing.mean == pytest.approx(300_000)


def test_a_real_jump_restarts_the_forecast_and_noise_does_not():
    random = np.random.default_rng(7)
    noise = 10_000 * random.gamma(6, 1 / 6, size=50)
    moved = np.concatenate((noise, 25_000 * random.gamma(6, 1 / 6, size=10)))
    assert abs(stretch_start(moved) - 50) <= 1
    assert stretches(moved)[-1][1] == 60
    false = sum(
        stretch_start(10_000 * np.random.default_rng(seed).gamma(4, 1 / 4, size=60)) > 0
        for seed in range(100)
    )
    assert false <= 5
    assert stretch_start(np.zeros(40)) == 0 and stretch_start(np.array([])) == 0
    by_day = dict(zip(weeks(60), moved.astype(int).tolist(), strict=True))
    ahead = days(MONDAY + timedelta(weeks=60), 70)
    rate = everyday_rate(by_day, weeks(60), ahead, always, 20_000)
    assert rate.since is not None and abs((rate.since - weeks(60)[50]).days) <= 7
    assert rate.mean == pytest.approx(250_000, rel=0.2)


def test_a_move_restarts_the_forecast_before_the_numbers_can_show_it():
    past = weeks(42)
    by_day = {week: 8_000 if week < past[40] else 24_000 for week in past}
    ahead = days(past[-1] + timedelta(weeks=1), 70)
    unaware = everyday_rate(by_day, past, ahead, always, 24_000)
    aware = everyday_rate(by_day, past, ahead, always, 24_000, moved_on=past[40])
    assert aware.mean == pytest.approx(240_000)
    assert unaware.mean < 0.7 * aware.mean
    # Moved, and nothing recorded since: the school's estimate is all there is.
    fresh = everyday_rate(by_day, past, ahead, always, 24_000, moved_on=ahead[0])
    assert fresh.mean == pytest.approx(240_000) and fresh.since == ahead[0]


def test_steady_spending_is_remembered_longer_and_weights_stay_a_mixture():
    steady = 10_000 * np.random.default_rng(3).gamma(6, 1 / 6, size=80)
    learned = memory(steady, 10_000)
    assert sum(learned.weights.values()) == pytest.approx(1)
    assert learned.half_life > sum(HALF_LIVES) / len(HALF_LIVES)
    assert 1.0 <= learned.inflation <= 4.0
    short = memory(steady[:6], 10_000)
    assert len(set(short.weights.values())) == 1 and short.inflation == 1.0


def test_breaks_have_their_own_pace():
    past = weeks(60)
    by_day = {w: 40_000 if KIND(w) == "break" else 10_000 for w in past}
    term = everyday_rate(by_day, past, days(date(2027, 1, 4), 7), KIND, 10_000)
    rest = everyday_rate(by_day, past, days(date(2026, 12, 14), 7), KIND, 10_000)
    assert term.mean == pytest.approx(10_000)
    assert rest.mean > 2 * term.mean


def test_the_range_covers_what_happens_about_as_often_as_it_says():
    inside = 0
    for seed in range(120):
        random = np.random.default_rng(seed)
        series = 12_000 * random.gamma(5, 1 / 5, size=70)
        by_day = dict(zip(weeks(40), series[:40].astype(int).tolist(), strict=True))
        ahead = days(MONDAY + timedelta(weeks=40), 7 * 30)
        rate = everyday_rate(by_day, weeks(40), ahead, always, 12_000)
        inside += abs(series[40:].sum() - rate.mean) <= 1.2816 * rate.variance**0.5
    assert 0.75 <= inside / 120 <= 0.99


def test_one_offs_move_from_the_schools_figure_to_the_students_own():
    ahead = days(MONDAY + timedelta(weeks=52), 140)
    flights = {MONDAY + timedelta(weeks=i): 50_000 for i in range(0, 52, 13)}
    few, many = weeks(5), weeks(52)
    early = one_off_rate(flights, few, ahead, [], 90_000, 50_000)
    late = one_off_rate(flights, many, ahead, [60_000], 90_000, 50_000)
    none = one_off_rate({}, [], ahead, [], 90_000, 50_000)
    assert none.mean == pytest.approx(90_000) and none.variance > 0
    pace = run_rate(flights, many, ahead, 52.0).mean
    assert late.mean == pytest.approx((pace + 60_000) / 2)
    assert min(90_000, pace) < early.mean < max(90_000, run_rate(flights, few, ahead, 52.0).mean)
    assert one_off_rate(flights, many, [], [], 90_000, 1).mean == 0
