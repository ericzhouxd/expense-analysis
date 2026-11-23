"""The budget as it would have been at the time, from what was recorded by then.

Replaying answers two questions. How far off was the projection at this point of
earlier school years? And what safe weekly amount did each Monday start with?
Nothing here is stored: results live in memory and are forgotten with the app.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import partial
from threading import Lock
from typing import Any

from .autopilot import AutoBudget, resolve
from .coa_outlook import coa_outlook, project, published_for
from .patterns import Row, Span, day_of
from .term_budget import (
    BudgetSettings,
    CoaProfile,
    monday,
    school_year_for,
    school_years_back_to,
    weekly_line,
)
from .university_presets import UCLA_2026

# However tight the year gets, a line below this share of UCLA's helps nobody.
LINE_FLOOR = 0.5
# A ledger may start this long after a year does and still show all of it.
LATE_START = timedelta(days=21)
# After this long nothing more of a finished year is still to be paid.
SETTLED = timedelta(days=45)
# Earlier years' misses count against this many years of being as sure as expected.
SPREAD_WEIGHT, SPREAD_LIMIT = 3.0, 3.0

_CACHE_SIZE = 1024
_cache: OrderedDict[str, Any] = OrderedDict()
_lock = Lock()


@dataclass(frozen=True)
class SmartBudget:
    """Everything the budget pages need, worked out from the ledger."""

    auto: AutoBudget
    # The safe weekly amount each Monday of this school year set.
    lines: dict[date, int]
    # How the projection did at this point of earlier school years.
    record: list[dict[str, Any]]


class _Past:
    """The ledger as it stood on any day, with a fingerprint of it."""

    def __init__(
        self,
        saved: BudgetSettings | None,
        rules: dict[str, Any],
        rows: list[Row],
        fixed: Iterable[str],
    ) -> None:
        self.saved, self.rules, self.fixed = saved, rules, frozenset(fixed)
        self.rows = sorted(rows, key=lambda row: (day_of(row), str(row["id"])))
        self.days = [day_of(row) for row in self.rows]
        self.settings = json.dumps(
            [saved.to_dict() if saved else None, rules, sorted(self.fixed)], sort_keys=True
        )
        digest = hashlib.blake2b(digest_size=16)
        self.prints = [digest.hexdigest()]
        for row in self.rows:
            fields = (
                *(row["id"], row["transaction_date"], row["amount_cents"], row["category"]),
                *(row["transaction_type"], row.get("description"), row.get("merchant")),
            )
            digest.update(repr(fields).encode())
            self.prints.append(digest.hexdigest())

    def rows_on(self, day: date) -> list[Row]:
        return self.rows[: bisect_right(self.days, day)]

    def remember(self, what: str, day: date, make: Callable[[], Any]) -> Any:
        """``make()``, unless it was worked out before from the very same records."""
        text = f"{what}|{day}|{self.prints[bisect_right(self.days, day)]}|{self.settings}"
        key = hashlib.blake2b(text.encode(), digest_size=16).hexdigest()
        with _lock:
            if key in _cache:
                _cache.move_to_end(key)
                return _cache[key]
        value = make()
        with _lock:
            _cache[key] = value
            while len(_cache) > _CACHE_SIZE:
                _cache.popitem(last=False)
        return value


def _safe_amount(past: _Past, week: date) -> int | None:
    rows = past.rows_on(week - timedelta(days=1))
    # The year's first Monday belongs to it even though the Sunday before didn't.
    day = (
        week
        if school_year_for(week - timedelta(days=1)) != school_year_for(week)
        else (week - timedelta(days=1))
    )
    auto = resolve(past.saved, past.rules, rows, day, past.fixed)
    outlook = coa_outlook(auto.settings, rows, day, auto.rules, auto.habits)
    if not outlook["ready"] or not outlook["weekly"]:
        return None
    school = weekly_line(auto.settings)["school_weekly"]
    return int(max(outlook["weekly"]["sure"], school * LINE_FLOOR)) // 100 * 100


def _year_total(past: _Past, span: Span, day: date, profile: CoaProfile) -> tuple[int, float]:
    """What the projection says about a school year on ``day``, and its spread."""
    rows = past.rows_on(day)
    # Saved settings describe the student today, not back then.
    auto = resolve(None, past.rules, rows, day, past.fixed)
    published = published_for(auto.settings.coa or profile, auto.settings.housing)
    year = project(auto.settings, rows, day, auto.rules, span, published, auto.habits)
    return year["projected"], math.sqrt(year["variance"])


def _track_record(past: _Past, as_of: date, profile: CoaProfile) -> list[dict[str, Any]]:
    span = school_year_for(as_of)
    if span is None or not past.days or not span[0] <= as_of < span[1]:
        return []
    first = past.days[0]
    result = []
    for earlier in school_years_back_to(span, first)[1:]:
        settled = earlier[1] + SETTLED
        if first > earlier[0] + LATE_START or settled > as_of:
            continue
        then = as_of - (span[0] - earlier[0])
        key = f"year {earlier[0]} {profile}"
        actual, _ = past.remember(
            key, settled, partial(_year_total, past, earlier, settled, profile)
        )
        guess, deviation = past.remember(
            key, then, partial(_year_total, past, earlier, then, profile)
        )
        if actual <= 0:
            continue
        result.append(
            {
                "label": f"{earlier[0].year}–{str(earlier[0].year + 1)[2:]}",
                "projected": guess,
                "actual": actual,
                "miss": guess - actual,
                "percent": abs(guess - actual) / actual * 100,
                "spreads": (guess - actual) / deviation if deviation > 0 else 0.0,
            }
        )
    return result


def smart_budget(
    saved: BudgetSettings | None,
    rules: dict[str, Any] | None,
    rows: list[Row],
    as_of: date,
    fixed: Iterable[str] = (),
) -> SmartBudget:
    """Settle every setting from the ledger and check the projection against the past."""
    past = _Past(saved, rules or {}, rows, fixed)
    auto = resolve(saved, rules, rows, as_of, past.fixed)
    span = school_year_for(as_of)

    lines: dict[date, int] = {}
    if span and not (saved and saved.weekly_cents):
        week = monday(span[0])
        while week <= monday(as_of):
            safe = past.remember(
                "line", week - timedelta(days=1), partial(_safe_amount, past, week)
            )
            if safe is not None:
                lines[week] = safe
            week += timedelta(weeks=1)

    profile = auto.settings.coa or CoaProfile(next(iter(UCLA_2026["cohorts"])), False, True)
    record = _track_record(past, as_of, profile)
    if record:
        squares = sum(item["spreads"] ** 2 for item in record)
        spread = math.sqrt((squares + SPREAD_WEIGHT) / (len(record) + SPREAD_WEIGHT))
        habits = replace(auto.habits, spread=min(SPREAD_LIMIT, max(1.0, spread)))
        auto = replace(auto, habits=habits)
    return SmartBudget(auto, lines, record)
