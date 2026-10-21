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
    from .categories import preferences

    removed = (
        (preferences(database) if hasattr(database, "connect") else {})
        .get("removed", {})
        .get(kind, [])
    )
    values = [v for v in defaults[kind] if v not in removed] + saved
    if kind == "account":
        values.insert(0, config.default_account)
    elif kind == "payment_method":
        values.insert(0, config.default_payment_method)
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


def unused_choices(database: Database, config: AppConfig, kind: str) -> list[str]:
    """Only offer values that no transaction, bill, rule, or entry default needs."""
    used = set(database.list_choice_values(kind))
    if kind == "category":
        used.add("Uncategorized")
        used.update(value for _, value in config.category_rules)
        plan = database.get_spending_plan()
        if plan:
            used.update(value for cost in plan.commitments for value in cost.categories)
    elif kind == "account":
        used.add(config.default_account)
    elif kind == "payment_method":
        used.add(config.default_payment_method)
    return [value for value in choice_options(database, config, kind) if value not in used]


def remove_unused_choices(
    database: Database, config: AppConfig, kind: str, values: list[str]
) -> None:
    """Persist tombstones so configured defaults do not reappear on the next run."""
    import json

    from .categories import preferences

    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not set(values).issubset(unused_choices(database, config, kind)):
            raise ValueError("A selected choice is in use. Reload and select unused choices.")
        settings = preferences(database)
        removed = settings.setdefault("removed", {})
        removed[kind] = sorted(set(removed.get(kind, [])) | set(values))
        connection.execute(
            "INSERT INTO category_settings(id,payload) VALUES(1,?) ON "
            "CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(settings, ensure_ascii=False),),
        )
