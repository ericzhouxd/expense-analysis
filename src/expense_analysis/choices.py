"""Shared editable vocabulary for transaction and budget forms."""

from .config import AppConfig
from .database import Database


def choice_options(database: Database, config: AppConfig, kind: str) -> list[str]:
    defaults = {
        "category": config.categories,
        "account": config.accounts,
        "payment_method": config.payment_methods,
    }
    if kind not in defaults:
        raise ValueError("This field uses fixed choices")
    # Keep custom values usable throughout the app, including imported values. Prefer the
    # database's DISTINCT query; fall back for proxies that only expose list_transactions().
    reader = getattr(database, "list_choice_values", None)
    saved = (
        reader(kind)
        if reader is not None
        else [str(row[kind]) for row in database.list_transactions()]
    )
    values = [*defaults[kind], *saved]
    if kind == "category":
        plan = database.get_spending_plan()
        if plan:
            values.extend(category for cost in plan.commitments for category in cost.categories)
    unique: dict[str, str] = {}
    for value in values:
        clean = value.strip()
        if clean:
            # Category matching is exact throughout filters and spending plans.
            unique.setdefault(clean, clean)
    return list(unique.values())
