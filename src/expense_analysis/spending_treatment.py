"""One classification for budgets, analytics and the CLI.

Every purchase counts as Everyday (inside the weekly line), Commitments (bills)
or Irregular (big one-off costs). Storage keeps these names; the interface calls
them Everyday, Bills and Big stuff.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .term_budget import BudgetSettings

TREATMENTS = ("Everyday", "Commitments", "Irregular")
CATEGORY_DEFAULT = "Use category default"


def validate_rules(rules: dict) -> dict:
    if set(rules) - {"categories", "transactions"}:
        raise ValueError("Unknown spending rule field.")
    for category, treatment in rules.get("categories", {}).items():
        if not category.strip() or treatment not in TREATMENTS:
            raise ValueError("Choose a valid category and spending treatment.")
    for identifier, rule in rules.get("transactions", {}).items():
        if not identifier or rule.get("treatment") not in TREATMENTS:
            raise ValueError("Choose a valid transaction treatment.")
    return rules


def apply_transaction_treatment(rules: dict, transaction_ids: list[str], treatment: str) -> dict:
    """Return ``rules`` with an exception set (or cleared) for each transaction."""
    if not transaction_ids:
        raise ValueError("Tick at least one transaction to update.")
    if treatment != CATEGORY_DEFAULT and treatment not in TREATMENTS:
        raise ValueError("Choose Everyday, Bills or Big stuff.")
    updated = {**rules, "transactions": dict(rules.get("transactions", {}))}
    for identifier in transaction_ids:
        if treatment == CATEGORY_DEFAULT:
            updated["transactions"].pop(identifier, None)
        else:
            updated["transactions"][identifier] = {"treatment": treatment}
    return validate_rules(updated)


def classify_spending(
    rows: list[dict[str, Any]], budget: BudgetSettings | None, rules: dict | None = None
) -> list[dict[str, Any]]:
    """Transaction exceptions win, then saved category choices, then bill categories.

    Categories nobody has reviewed count as Everyday and carry a review flag, so
    they use up the weekly line instead of silently disappearing from it.
    """
    rules = validate_rules(rules or {})
    categories = rules.get("categories", {})
    overrides = rules.get("transactions", {})
    defaults = dict.fromkeys(budget.bill_categories, "Commitments") if budget else {}
    result = []
    for row in rows:
        category = row["category"]
        override = overrides.get(row["id"], {})
        treatment = override.get("treatment", categories.get(category, defaults.get(category)))
        result.append(
            {
                **row,
                "spending_treatment": treatment or "Everyday",
                "treatment_review": treatment is None,
            }
        )
    return result
