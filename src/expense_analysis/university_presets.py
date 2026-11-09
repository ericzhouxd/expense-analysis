"""Public, versioned reference data. Never store student information here."""

from typing import TypedDict


class CohortRates(TypedDict):
    tuition: int
    nrst: int


class UclaPreset(TypedDict):
    id: str
    school: str
    academic_year: str
    source: str
    verified_on: str
    months: int
    campus_fees: int
    insurance: int
    cohorts: dict[str, CohortRates]
    housing: dict[str, dict[str, int]]


UCLA_2026: UclaPreset = {
    "id": "ucla-undergraduate-2026-27-v1",
    "school": "UCLA",
    "academic_year": "2026–27",
    "source": "https://financialaid.ucla.edu/go/coa",
    "verified_on": "2026-09-08",
    "months": 9,
    "campus_fees": 84200,
    "insurance": 388500,
    "cohorts": {
        "2024–25": {"tuition": 1443600, "nrst": 3420000},
        "2025–26": {"tuition": 1493400, "nrst": 3760200},
        "2026–27": {"tuition": 1558800, "nrst": 3927000},
    },
    "housing": {
        "Off-campus": {
            "Housing": 1454100,
            "Food": 661000,
            "Books": 158800,
            "Transportation": 158300,
            "Personal": 314800,
            # UCLA's displayed off-campus total is $1 above its component sum.
            "Published total reconciliation": 100,
        },
        "On-campus": {
            "Housing": 1229900,
            "Food": 756800,
            "Books": 158800,
            "Transportation": 96900,
            "Personal": 276100,
        },
        "Commuter": {
            "Housing": 395500,
            "Food": 483400,
            "Books": 158800,
            "Transportation": 288300,
            "Personal": 313200,
        },
    },
}


def ucla_benchmark(cohort: str, housing: str, nonresident: bool) -> dict[str, int]:
    """Return a fresh component snapshot, in cents, for the nine-month benchmark."""
    rates = UCLA_2026["cohorts"][cohort]
    return {
        "Tuition + student services": rates["tuition"],
        "Nonresident tuition": rates["nrst"] if nonresident else 0,
        "Campus fees": UCLA_2026["campus_fees"],
        "Insurance": UCLA_2026["insurance"],
        **UCLA_2026["housing"][housing],
    }


class QuarterDates(TypedDict):
    name: str
    quarter_begins: str
    instruction_begins: str
    finals_begin: str
    quarter_ends: str


# UCLA Registrar annual academic calendars, read 2026-11-09 from
# https://registrar.ucla.edu/calendars/annual-academic-calendar. Each quarter is
# ten weeks of instruction plus finals week; fall adds a short Week 0.
UCLA_CALENDAR_SOURCE = "https://registrar.ucla.edu/calendars/annual-academic-calendar"
UCLA_QUARTERS: tuple[QuarterDates, ...] = (
    {
        "name": "Fall 2025",
        "quarter_begins": "2025-09-22",
        "instruction_begins": "2025-09-25",
        "finals_begin": "2025-12-08",
        "quarter_ends": "2025-12-12",
    },
    {
        "name": "Winter 2026",
        "quarter_begins": "2026-01-02",
        "instruction_begins": "2026-01-05",
        "finals_begin": "2026-03-16",
        "quarter_ends": "2026-03-20",
    },
    {
        "name": "Spring 2026",
        "quarter_begins": "2026-03-25",
        "instruction_begins": "2026-03-30",
        "finals_begin": "2026-06-08",
        "quarter_ends": "2026-06-12",
    },
    {
        "name": "Fall 2026",
        "quarter_begins": "2026-09-21",
        "instruction_begins": "2026-09-24",
        "finals_begin": "2026-12-07",
        "quarter_ends": "2026-12-11",
    },
    {
        "name": "Winter 2027",
        "quarter_begins": "2027-01-04",
        "instruction_begins": "2027-01-04",
        "finals_begin": "2027-03-15",
        "quarter_ends": "2027-03-19",
    },
    {
        "name": "Spring 2027",
        "quarter_begins": "2027-03-24",
        "instruction_begins": "2027-03-29",
        "finals_begin": "2027-06-07",
        "quarter_ends": "2027-06-11",
    },
)
# Summer Sessions 2027 run June 21 – September 10.
UCLA_SUMMER_ENDS = {"2027": "2027-09-12"}

# Living costs a student pays week to week. Housing is a bill; books arrive
# once a quarter, so they are shown separately.
EVERYDAY_COMPONENTS = ("Food", "Transportation", "Personal")


def everyday_estimate(housing: str) -> dict[str, int]:
    """UCLA's nine-month everyday living estimate, in cents, by component."""
    if housing not in UCLA_2026["housing"]:
        raise ValueError("Choose a listed housing type.")
    components = UCLA_2026["housing"][housing]
    return {name: components[name] for name in (*EVERYDAY_COMPONENTS, "Books")}
