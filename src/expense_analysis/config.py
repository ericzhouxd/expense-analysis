from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Overridable so a check can run against a throwaway directory instead of the
# real ledger. Nothing else in the app reads these variables.
DATA_DIR = Path(os.environ.get("EXPENSE_ANALYSIS_DATA_DIR", PROJECT_ROOT / "data"))
OUTPUT_DIR = Path(os.environ.get("EXPENSE_ANALYSIS_OUTPUT_DIR", PROJECT_ROOT / "output"))
DATABASE_PATH = DATA_DIR / "expenses.sqlite3"
LOCAL_CONFIG_PATH = PROJECT_ROOT / "config.toml"

DEFAULT_PERSONAL_CATEGORIES = (
    "Food",
    "Dining Out",
    "Entertainment",
    "Transportation",
    "Daily Necessities",
    "Sports",
    "Clothes",
    "Cell Phone",
    "Laundry",
    "Medicine",
    "Church",
    "Tech",
    "Stationary",
)
DEFAULT_FIXED_CATEGORIES = (
    "Tuition",
    "Rent",
    "Utilities",
    "Internet",
    "Housing and Meal Plan",
    "School Fees",
    "Insurance",
    "Flight",
    "Hotel",
    "Travel",
)
DEFAULT_ACCOUNTS = ("Checking", "Credit Card", "Cash")
DEFAULT_METHODS = ("Card", "Mobile Wallet", "Bank Transfer", "Online", "Cash")
TRANSACTION_TYPES = ("expense", "refund", "income", "transfer")


@dataclass(frozen=True)
class AcademicPeriod:
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class AcademicCalendar:
    fall_months: tuple[int, ...] = (9, 10, 11, 12)
    winter_months: tuple[int, ...] = (1, 2, 3)
    spring_months: tuple[int, ...] = (4, 5, 6)
    summer_months: tuple[int, ...] = (7, 8)
    explicit_periods: tuple[AcademicPeriod, ...] = ()

    def label_for(self, value: date) -> str:
        for period in self.explicit_periods:
            if period.start <= value <= period.end:
                return period.label
        year = value.year
        month = value.month
        if month in self.fall_months:
            return f"Fall {year}"
        if month in self.winter_months:
            return f"Winter {year}"
        if month in self.spring_months:
            return f"Spring {year}"
        if month in self.summer_months:
            return f"Summer {year}"
        return f"Unassigned {year}"


@dataclass(frozen=True)
class AppConfig:
    personal_categories: tuple[str, ...] = DEFAULT_PERSONAL_CATEGORIES
    fixed_categories: tuple[str, ...] = DEFAULT_FIXED_CATEGORIES
    accounts: tuple[str, ...] = DEFAULT_ACCOUNTS
    payment_methods: tuple[str, ...] = DEFAULT_METHODS
    default_account: str = "Checking"
    default_payment_method: str = "Card"
    category_rules: tuple[tuple[str, str], ...] = ()
    academic_calendar: AcademicCalendar = field(default_factory=AcademicCalendar)

    @property
    def categories(self) -> tuple[str, ...]:
        return self.personal_categories + self.fixed_categories + ("Uncategorized",)

    def spending_class(self, category: str) -> str:
        if category in self.fixed_categories:
            return "Fixed"
        if category in self.personal_categories:
            return "Personal"
        return "Uncategorized"

    def category_for(self, description: str, merchant: str = "", provided: str = "") -> str:
        if provided in self.categories:
            return provided
        searchable = f"{description} {merchant}".casefold()
        for keyword, category in self.category_rules:
            if keyword.casefold() in searchable and category in self.categories:
                return category
        return "Uncategorized"


def _tuple_setting(section: dict[str, Any], key: str, default: tuple[Any, ...]) -> tuple[Any, ...]:
    value = section.get(key, default)
    if not isinstance(value, list | tuple):
        raise ValueError(f"{key} must be a TOML array")
    return tuple(value)


def load_config(path: Path = LOCAL_CONFIG_PATH) -> AppConfig:
    if not path.exists():
        return AppConfig()

    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    categories = raw.get("categories", {})
    choices = raw.get("choices", {})
    defaults = raw.get("defaults", {})
    calendar = raw.get("academic_calendar", {})
    explicit_periods = tuple(
        AcademicPeriod(
            label=str(period["label"]),
            start=date.fromisoformat(str(period["start"])),
            end=date.fromisoformat(str(period["end"])),
        )
        for period in raw.get("academic_periods", [])
    )

    academic_calendar = AcademicCalendar(
        fall_months=_tuple_setting(calendar, "fall_months", (9, 10, 11, 12)),
        winter_months=_tuple_setting(calendar, "winter_months", (1, 2, 3)),
        spring_months=_tuple_setting(calendar, "spring_months", (4, 5, 6)),
        summer_months=_tuple_setting(calendar, "summer_months", (7, 8)),
        explicit_periods=explicit_periods,
    )
    return AppConfig(
        personal_categories=_tuple_setting(categories, "personal", DEFAULT_PERSONAL_CATEGORIES),
        fixed_categories=_tuple_setting(categories, "fixed", DEFAULT_FIXED_CATEGORIES),
        accounts=_tuple_setting(choices, "accounts", DEFAULT_ACCOUNTS),
        payment_methods=_tuple_setting(choices, "payment_methods", DEFAULT_METHODS),
        default_account=str(defaults.get("account", "Checking")),
        default_payment_method=str(defaults.get("payment_method", "Card")),
        category_rules=tuple(
            (str(keyword), str(category))
            for keyword, category in raw.get("category_rules", {}).items()
        ),
        academic_calendar=academic_calendar,
    )


def ensure_local_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
