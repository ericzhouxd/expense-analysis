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
