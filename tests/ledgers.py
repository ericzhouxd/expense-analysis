"""Made-up ledgers shared by the tests. No amount, name or date comes from a real one."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

Row = dict[str, Any]


def row(
    identifier: str,
    day: date | str,
    amount: int,
    category: str = "Food",
    description: str = "",
    kind: str = "expense",
) -> Row:
    return {
        "id": identifier,
        "transaction_date": day if isinstance(day, str) else day.isoformat(),
        "description": description or category,
        "merchant": "",
        "amount_cents": amount,
        "category": category,
        "transaction_type": kind,
    }


def weekly(
    amount: int,
    first: date,
    last: date,
    category: str = "Food",
    name: str = "groceries",
) -> list[Row]:
    """The same spending every Wednesday, in four purchases so none looks big."""
    rows = []
    day = first - timedelta(days=first.weekday()) + timedelta(days=2)
    while day <= last:
        for part in range(4):
            share = amount // 4 + (1 if part < amount % 4 else 0)
            rows.append(row(f"{name}{day}{part}", day, share, category, f"{name} {part} {day}"))
        day += timedelta(days=7)
    return rows


def monthly(amount: int, months: list[str], day: int, category: str, description: str) -> list[Row]:
    return [
        row(f"{description}{month}", f"{month}-{day:02d}", amount, category, description)
        for month in months
    ]


def student() -> list[Row]:
    """Two school years: a dorm with a meal plan, then an apartment.

    A nonresident who entered in fall 2025, waived UC SHIP and pays by the quarter.
    """
    rows = []
    for number, day in enumerate(("2025-08-30", "2025-12-18", "2026-03-10", "2026-08-30")):
        rows.append(row(f"tuition{number}", day, 17_850_00, "Tuition", f"Tuition {day}"))
    for number, day in enumerate(("2025-09-10", "2025-12-18", "2026-03-10")):
        rows.append(row(f"room{number}", day, 6_000_00, "Campus Housing", f"Housing {day}"))
    rows += monthly(900_00, ["2026-09", "2026-10", "2026-11"], 1, "Rent", "Rent to landlord")
    rows += monthly(
        11_99,
        [f"2025-{m:02d}" for m in (10, 11, 12)] + [f"2026-{m:02d}" for m in range(1, 12)],
        8,
        "Entertainment",
        "Streaming service",
    )
    rows += [
        row("insurance1", "2025-08-05", 900_00, "Insurance", "Student health plan 25-26"),
        row("insurance2", "2026-08-03", 930_00, "Insurance", "Student health plan 26-27"),
        row("flight1", "2025-12-01", 420_00, "Flight", "Home for winter"),
        row("flight2", "2026-03-01", 260_00, "Flight", "Spring break"),
        row("flight3", "2026-05-20", 450_00, "Flight", "Home for summer"),
        row("flight4", "2026-09-01", 310_00, "Flight", "Back to campus"),
        row("monitor", "2026-01-15", 240_00, "Tech", "Monitor"),
    ]
    rows += weekly(60_00, date(2025, 9, 15), date(2026, 6, 12), "Dining Out", "snacks")
    rows += weekly(210_00, date(2026, 9, 21), date(2026, 11, 20), "Groceries", "market")
    return rows
