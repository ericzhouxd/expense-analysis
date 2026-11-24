"""Forecasting from a student's own weeks, trained on them every time it runs.

Day-to-day spending is steady until life changes (a new apartment, a meal plan
ending) and then jumps. So the forecast remembers for a long time but starts over
at a jump: ``stretch_start`` finds it, and ``memory`` picks how long to remember
by replaying the weeks already recorded. The range is widened by how wrong those
replays were.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from numpy.typing import NDArray

Values = NDArray[np.float64]

# Weeks until a past week counts half as much; replays decide between them.
HALF_LIVES = (6.0, 13.0, 26.0, 52.0)
REPLAY_WEEKS = 8
REPLAY_MINIMUM = 8
# A jump must be this unlikely to be chance, and at least this large.
JUMP_SCORE, JUMP_SIZE = 4.0, 0.25
JUMP_BEFORE, JUMP_AFTER, JUMP_MEMORY = 6, 4, 30
# Until there is history, the school's estimate counts as one week of it.
PRIOR_WEEKS = 1.0
# How uneven a student's weeks are before their own say so.
PRIOR_SPREAD, PRIOR_SPREAD_WEEKS = 0.4, 2.0
# How far the level wanders over the months ahead, as a share of itself, and how
# much further it can shift with a new school year before the weeks show it.
DRIFT, FRESH_YEAR, FRESH_WEEKS = 0.12, 0.25, 8.0
# Breaks seen for a week or two are pulled toward an ordinary week.
KIND_SHRINK_WEEKS = 2.0
ONE_OFF_HALF_LIFE = 52.0
# Less than half a year of one-off purchases says little about the rest of it.
ONE_OFF_MINIMUM_WEEKS = 26
CALIBRATION_WEIGHT, CALIBRATION_LIMIT = 4.0, 4.0


@dataclass(frozen=True)
class RunRate:
    """Spending expected over the days ahead, in cents."""

    mean: float
    variance: float
    weeks: int
    # What an ordinary week of classes costs.
    level: float = 0.0
    # The week the current stretch began, when a jump was found.
    since: date | None = None


def weekly_totals(by_day: dict[date, int], weeks: list[date]) -> Values:
    return np.array(
        [sum(by_day.get(week + timedelta(days=i), 0) for i in range(7)) for week in weeks],
        dtype=float,
    )


def _drift(half_life: float, count: float) -> float:
    """Extra weeks' worth of variance because the level itself wanders."""
    alpha = 1 - 0.5 ** (1 / half_life)
    return float(alpha * alpha / (1 - alpha) * count * (count + 1) * (2 * count + 1) / 6)


def run_rate(
    by_day: dict[date, int], weeks: list[date], ahead: list[date], half_life: float
) -> RunRate:
    """Project the days ``ahead`` at the recency-weighted average of past ``weeks``."""
    if not weeks or not ahead:
        return RunRate(0.0, 0.0, len(weeks))
    totals = weekly_totals(by_day, weeks)
    weights = 0.5 ** ((len(totals) - 1 - np.arange(len(totals))) / half_life)
    weights /= weights.sum()
    level = float(weights @ totals)
    effective = 1 / float(weights @ weights)
    spread = float(weights @ (totals - level) ** 2) * effective / max(effective - 1, 1)
    count = len(ahead) / 7
    return RunRate(
        max(0.0, level * count),
        spread * (count + _drift(half_life, count) + count * count / effective),
        len(weeks),
        max(0.0, level),
    )


def _jump(roots: Values) -> int | None:
    """Where the mean most clearly changes, if it clearly does."""
    n = len(roots)
    splits = np.arange(JUMP_BEFORE, n - JUMP_AFTER + 1)
    if not len(splits):
        return None
    sums = np.concatenate(([0.0], np.cumsum(roots)))
    squares = np.concatenate(([0.0], np.cumsum(roots * roots)))
    first = np.maximum(0, splits - JUMP_MEMORY)
    before, after = splits - first, n - splits
    mean_before = (sums[splits] - sums[first]) / before
    mean_after = (sums[n] - sums[splits]) / after
    var_before = np.maximum(0, (squares[splits] - squares[first]) / before - mean_before**2)
    var_after = np.maximum(0, (squares[n] - squares[splits]) / after - mean_after**2)
    # Perfectly even weeks would make any difference look certain.
    floor = (0.1 * np.maximum(mean_before, mean_after)) ** 2 + 1e-9
    error = np.sqrt(
        np.maximum(var_before, floor) / np.maximum(before - 1, 1)
        + np.maximum(var_after, floor) / np.maximum(after - 1, 1)
    )
    score = np.abs(mean_after - mean_before) / error
    larger = np.maximum(mean_before, mean_after) ** 2
    size = np.abs(mean_after**2 - mean_before**2) / np.maximum(larger, 1e-9)
    score = np.where(size >= JUMP_SIZE, score, 0.0)
    best = int(np.argmax(score))
    return int(splits[best]) if score[best] >= JUMP_SCORE else None


def stretch_start(values: Values) -> int:
    """The index where the current stretch of similar weeks begins."""
    start = 0
    roots = np.sqrt(np.maximum(values, 0))
    while (jump := _jump(roots[start:])) is not None:
        start += jump
    return start


def _level(values: Values, half_life: float, prior: float) -> tuple[float, float]:
    """The weighted level and how many weeks it effectively rests on."""
    weights = 0.5 ** ((len(values) - 1 - np.arange(len(values))) / half_life)
    total = float(weights.sum()) + PRIOR_WEEKS
    level = (float(weights @ values) + PRIOR_WEEKS * prior) / total
    squares = float(weights @ weights) + PRIOR_WEEKS**2
    return level, total * total / squares


def _spread(values: Values, level: float) -> float:
    """Week-to-week variance, leaning on a typical unevenness while weeks are few."""
    usual = (PRIOR_SPREAD * level) ** 2
    squares = float(((values - level) ** 2).sum()) if len(values) else 0.0
    return (squares + PRIOR_SPREAD_WEEKS * usual) / (len(values) + PRIOR_SPREAD_WEEKS)


@dataclass(frozen=True)
class Memory:
    """What replaying the past taught: how long to remember, and how wrong it tends to be."""

    weights: dict[float, float]
    inflation: float

    @property
    def half_life(self) -> float:
        return sum(half_life * weight for half_life, weight in self.weights.items())

    def level(self, values: Values, prior: float) -> tuple[float, float]:
        pairs = [
            (weight, *_level(values, half_life, prior))
            for half_life, weight in self.weights.items()
        ]
        return (
            sum(weight * level for weight, level, _ in pairs),
            sum(weight * effective for weight, _, effective in pairs),
        )


def stretches(values: Values) -> list[tuple[int, int]]:
    """Every stretch of similar weeks, oldest first, as index ranges."""
    ends = [len(values)]
    while (start := stretch_start(values[: ends[-1]])) > 0:
        ends.append(start)
    starts = [*ends[1:], 0]
    return list(zip(reversed(starts), reversed(ends), strict=True))


def memory(values: Values, prior: float) -> Memory:
    """Replay the recorded weeks and keep what would have forecast them best.

    Replays stay inside one stretch. A jump is handled by starting over, so it
    should neither shorten the memory nor widen the range.
    """
    even = dict.fromkeys(HALF_LIVES, 1 / len(HALF_LIVES))
    errors: dict[float, list[float]] = {half_life: [] for half_life in HALF_LIVES}
    scores: list[float] = []
    for first, last in stretches(values):
        for at in range(first + REPLAY_MINIMUM, last - 1):
            seen = values[first:at]
            coming = values[at : min(last, at + REPLAY_WEEKS)]
            actual = float(coming.mean())
            levels = {half_life: _level(seen, half_life, prior) for half_life in HALF_LIVES}
            for half_life, (level, _) in levels.items():
                errors[half_life].append((level - actual) ** 2)
            middle = sum(level for level, _ in levels.values()) / len(levels)
            effective = sum(count for _, count in levels.values()) / len(levels)
            expected = _spread(seen, middle) * (1 / len(coming) + 1 / effective)
            if expected > 0:
                scores.append((middle - actual) ** 2 / expected)
    if len(scores) < REPLAY_MINIMUM:
        return Memory(even, 1.0)
    means = {half_life: float(np.mean(misses)) for half_life, misses in errors.items()}
    smallest = min(means.values())
    raw = {h: (smallest + 1) ** 2 / (miss + 1) ** 2 for h, miss in means.items()}
    weights = {h: value / sum(raw.values()) for h, value in raw.items()}
    # Neighboring replays share weeks, so they count as fewer than they are.
    independent = len(scores) / REPLAY_WEEKS
    inflation = (float(np.mean(scores)) * independent + CALIBRATION_WEIGHT) / (
        independent + CALIBRATION_WEIGHT
    )
    return Memory(weights, min(CALIBRATION_LIMIT, max(1.0, inflation)))


def everyday_rate(
    by_day: dict[date, int],
    weeks: list[date],
    ahead: list[date],
    kind_of: Callable[[date], str | None],
    prior_weekly: float,
    moved_on: date | None = None,
    year_starts: date | None = None,
) -> RunRate:
    """Project day-to-day spending over the days ``ahead``.

    The level comes from class weeks of the current stretch, which starts at the
    last jump or at a move (``moved_on``). Breaks and summer are scaled by how
    such weeks compared with class weeks of their own stretch. ``prior_weekly``
    is the school's estimate, the only guess before any history. A year that has
    only begun (``year_starts``) may yet turn out different from the last one.
    """
    if not ahead:
        return RunRate(0.0, 0.0, len(weeks), prior_weekly)
    totals = weekly_totals(by_day, weeks)
    kinds = [kind_of(week) for week in weeks]
    ordinary = [i for i, kind in enumerate(kinds) if kind not in ("break", "summer")]
    values = totals[ordinary]
    start = stretch_start(values)
    if moved_on is not None:
        start = max(start, sum(1 for i in ordinary if weeks[i] + timedelta(days=6) < moved_on))
    learned = memory(values, prior_weekly)
    current = values[start:]
    level, effective = learned.level(current, prior_weekly)
    level = max(0.0, level)

    since = None
    if start:
        since = weeks[ordinary[start]] if start < len(ordinary) else moved_on
    groups: dict[str | None, list[float]] = defaultdict(list)
    base_before = float(values[:start].mean()) if start else 0.0
    base_current = float(current.mean()) if len(current) else 0.0
    for week, total, kind in zip(weeks, totals, kinds, strict=True):
        base = base_before if since and week < since else base_current
        if kind in ("break", "summer") and base > 0:
            groups[kind].append(max(0.0, float(total) / base))
    factors = {
        kind: (sum(ratios) + KIND_SHRINK_WEEKS) / (len(ratios) + KIND_SHRINK_WEEKS)
        for kind, ratios in groups.items()
    }

    count = len(ahead) / 7
    scale = sum(factors.get(kind_of(day), 1.0) for day in ahead) / 7
    spread = _spread(current, level) * learned.inflation
    variance = spread * (
        (scale / count) ** 2 * (count + _drift(learned.half_life, count))
        + scale * scale / effective
    )
    seen = sum(1 for i in ordinary if year_starts is not None and weeks[i] >= year_starts)
    unsure = max(0.0, 1 - seen / FRESH_WEEKS) if year_starts is not None else 0.0
    variance += (level * scale) ** 2 * (DRIFT**2 + FRESH_YEAR**2 * unsure)
    return RunRate(level * scale, variance, len(weeks), level, since)


def one_off_rate(
    by_day: dict[date, int],
    weeks: list[date],
    ahead: list[date],
    same_stretch: list[int],
    neutral: float,
    neutral_spread: float,
) -> RunRate:
    """Project flights, trips and other big purchases over the days ``ahead``.

    They come in lumps at their own times of year, so what the same stretch of
    each earlier school year held counts alongside the overall pace. ``neutral``
    is the school's own figure; it fades out over the first half year.
    """
    if not ahead:
        return RunRate(0.0, 0.0, len(weeks))
    pace = run_rate(by_day, weeks, ahead, ONE_OFF_HALF_LIFE)
    known = min(1.0, len(weeks) / ONE_OFF_MINIMUM_WEEKS)
    estimates = np.array([pace.mean, *map(float, same_stretch)])
    between = float(estimates.var(ddof=1)) / len(estimates) if len(estimates) > 1 else 0.0
    mean = known * float(estimates.mean()) + (1 - known) * neutral
    variance = known**2 * (pace.variance + between) + (1 - known) ** 2 * neutral_spread**2
    # The two guesses disagreeing is uncertainty of its own.
    variance += known * (1 - known) * (pace.mean - neutral) ** 2
    return RunRate(max(0.0, mean), variance, len(weeks), pace.level)
