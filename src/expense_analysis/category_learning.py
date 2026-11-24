"""Which category a new entry most likely belongs to, going by earlier entries.

Nothing is stored or trained: the ledger is read each time. Recent entries count for
more than old ones, and entries whose category was set by hand for the most. The same
name decides first, then the words in it, then the merchant; whichever is not clear
enough to answer passes to the next.

The numbers below were chosen by replaying ledgers, predicting each entry from the
ones before it. They sit where nearby values do about as well.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

from .models import keyword_matches, name_tokens, normalize_text

UNCATEGORIZED = "Uncategorized"
HALF_LIFE_DAYS = 365
# A category set by hand says as much as this many entries left alone...
CORRECTION_WEIGHT = 3.0
# ...and what the same name was before it hardly counts any more.
SUPERSEDED_WEIGHT = 0.1
# How much of the evidence has to agree before there is an answer.
NAME_SHARE, WORD_SHARE, MERCHANT_SHARE = 0.6, 0.75, 0.8
# One recent entry with a word is enough to go by; one from over a year ago is not.
WORD_PRIOR, WORD_MINIMUM = 1.0, 0.4
MERCHANT_MINIMUM = 2
EVIDENCE_LIMIT = 4

_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


@dataclass(frozen=True)
class Evidence:
    """Earlier entries, or a rule, that speak for a category."""

    text: str
    category: str
    count: int = 0


@dataclass(frozen=True)
class Suggestion:
    category: str
    # rule, name, words, merchant, built-in, default or none.
    source: str
    evidence: tuple[Evidence, ...] = ()
    # How much of the evidence agrees.
    share: float = 1.0


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


@lru_cache(maxsize=16384)
def words_of(text: str) -> Mapping[str, str]:
    """What the words of a description are compared by, and how each was written.

    Scripts written without spaces are compared by pairs of characters.
    """
    found: dict[str, str] = {}
    for word in sorted(name_tokens(text)):
        if _CJK.search(word) and len(word) > 2:
            found.update((pair, pair) for pair in map("".join, zip(word, word[1:], strict=False)))
        else:
            found.setdefault(_stem(word), word)
    return found


def _pool(transaction_type: str) -> str:
    """Refunds are sorted like the purchases they undo, and nothing else is."""
    return "expense" if transaction_type == "refund" else transaction_type


def _name(text: str) -> object:
    """The same for "Rent October" and "Rent 11/1"."""
    return frozenset(words_of(text)) or normalize_text(text)


@dataclass
class _Entry:
    description: str
    name: object
    words: Mapping[str, str]
    merchant: str
    category: str
    weight: float


@dataclass
class _Tally:
    weights: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    counts: Counter[str] = field(default_factory=Counter)

    def add(self, entry: _Entry) -> None:
        self.weights[entry.category] += entry.weight
        self.counts[entry.category] += 1

    @property
    def total(self) -> float:
        return sum(self.weights.values())

    def best(self) -> tuple[str, float]:
        category, weight = min(self.weights.items(), key=lambda item: (-item[1], item[0]))
        return category, weight / self.total

    def evidence(self, text: str) -> list[Evidence]:
        ranked = sorted(self.weights.items(), key=lambda item: (-item[1], item[0]))
        return [Evidence(text, category, self.counts[category]) for category, _ in ranked]


class CategoryHistory:
    """Earlier entries, weighed as of a day."""

    def __init__(
        self,
        rows: Iterable[Mapping[str, Any]],
        corrections: Mapping[str, str],
        categories: Iterable[str],
        as_of: date,
    ) -> None:
        known = set(categories) - {UNCATEGORIZED}
        self._pools: dict[str, list[_Entry]] = defaultdict(list)
        kept = [row for row in rows if row["category"] in known]
        # The last category set by hand for each name, and when.
        settled: dict[object, tuple[str, str]] = {}
        for row in kept:
            at = corrections.get(str(row["id"]))
            if at is not None:
                key = (_pool(str(row["transaction_type"])), _name(str(row["description"])))
                settled[key] = max(settled.get(key, ("", "")), (at, str(row["category"])))
        for row in kept:
            pool, category = _pool(str(row["transaction_type"])), str(row["category"])
            description = str(row["description"])
            name = _name(description)
            at = corrections.get(str(row["id"]))
            # A category set by hand is as recent as the day it was set.
            day = date.fromisoformat((at or str(row["transaction_date"]))[:10])
            weight = 0.5 ** (max(0, (as_of - day).days) / HALF_LIFE_DAYS)
            if at is not None:
                weight *= CORRECTION_WEIGHT
            since, choice = settled.get((pool, name), ("", category))
            if category != choice and (at or str(row.get("created_at") or "")) <= since:
                weight *= SUPERSEDED_WEIGHT
            self._pools[pool].append(
                _Entry(
                    description,
                    name,
                    words_of(description),
                    normalize_text(str(row["merchant"])),
                    category,
                    weight,
                )
            )

    def suggest(
        self, description: str, merchant: str = "", transaction_type: str = "expense"
    ) -> Suggestion | None:
        entries = self._pools.get(_pool(transaction_type), [])
        return (
            self._by_name(entries, description)
            or self._by_words(entries, description)
            or self._by_merchant(entries, merchant)
        )

    def category_for(
        self, description: str, merchant: str = "", transaction_type: str = "expense"
    ) -> str | None:
        found = self.suggest(description, merchant, transaction_type)
        return found.category if found else None

    def mentions(self, keyword: str) -> bool:
        """Whether there are entries of its own to go by for a word."""
        return any(
            keyword_matches(keyword, entry.description)
            for entries in self._pools.values()
            for entry in entries
        )

    @staticmethod
    def _by_name(entries: list[_Entry], description: str) -> Suggestion | None:
        name, tally = _name(description), _Tally()
        if not name:
            return None
        for entry in entries:
            if entry.name == name:
                tally.add(entry)
        if not tally.weights:
            return None
        category, share = tally.best()
        if share < NAME_SHARE:
            return None
        evidence = tally.evidence(" ".join(description.split()))[:EVIDENCE_LIMIT]
        return Suggestion(category, "name", tuple(evidence), share)

    @staticmethod
    def _by_words(entries: list[_Entry], description: str) -> Suggestion | None:
        words = words_of(description)
        tallies: dict[str, _Tally] = defaultdict(_Tally)
        for entry in entries:
            for word in words.keys() & entry.words.keys():
                tallies[word].add(entry)
        votes: dict[str, float] = defaultdict(float)
        for tally in tallies.values():
            total = tally.total
            # A word used for many kinds of things says little about any of them.
            purity = sum((weight / total) ** 2 for weight in tally.weights.values())
            strength = total / (total + WORD_PRIOR) * purity
            for category, weight in tally.weights.items():
                votes[category] += strength * weight / total
        if not votes:
            return None
        category, vote = min(votes.items(), key=lambda item: (-item[1], item[0]))
        share = vote / sum(votes.values())
        if vote < WORD_MINIMUM or share < WORD_SHARE:
            return None
        ranked = sorted(tallies, key=lambda word: (-tallies[word].weights[category], word))
        evidence = [
            item
            for word in ranked
            for item in tallies[word].evidence(words[word])
            if item.category == category
        ]
        return Suggestion(category, "words", tuple(evidence[:EVIDENCE_LIMIT]), share)

    @staticmethod
    def _by_merchant(entries: list[_Entry], merchant: str) -> Suggestion | None:
        name, tally = normalize_text(merchant), _Tally()
        if not name:
            return None
        for entry in entries:
            if entry.merchant == name:
                tally.add(entry)
        if not tally.weights:
            return None
        category, share = tally.best()
        if share < MERCHANT_SHARE or tally.counts[category] < MERCHANT_MINIMUM:
            return None
        evidence = tally.evidence(" ".join(merchant.split()))[:EVIDENCE_LIMIT]
        return Suggestion(category, "merchant", tuple(evidence), share)
