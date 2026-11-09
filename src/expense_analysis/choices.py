"""Shared editable vocabulary for transaction and budget forms."""

from .config import AppConfig
from .database import Database


def choice_options(database: Database, config: AppConfig, kind: str) -> list[str]:
    from .categories import effective_config

    if hasattr(database, "connect"):
        config = effective_config(database, config)
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
        budget = database.get_budget_settings()
        if budget:
            values.extend(budget.bill_categories)
    unique: dict[str, str] = {}
    for value in values:
        clean = value.strip()
        if clean:
            # Category matching is exact throughout filters and spending plans.
            unique.setdefault(clean, clean)
    return list(unique.values())


def unused_choices(database: Database, config: AppConfig, kind: str) -> list[str]:
    """Only offer values that no transaction, bill, rule, or entry default needs."""
    from .categories import effective_config

    config = effective_config(database, config)
    used = set(database.list_choice_values(kind))
    if kind == "category":
        used.add("Uncategorized")
        used.update(value for _, value in config.category_rules)
        budget = database.get_budget_settings()
        if budget:
            used.update(budget.bill_categories)
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
        if kind == "category":
            for value in values:
                settings["classes"].pop(value, None)
                settings.get("spending_rules", {}).get("categories", {}).pop(value, None)
        connection.execute(
            "INSERT INTO category_settings(id,payload) VALUES(1,?) ON "
            "CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(settings, ensure_ascii=False),),
        )


def restore_choice(
    database: Database, kind: str, name: str, spending_class: str | None = None
) -> None:
    """Undo an unused-choice removal by lifting its tombstone (and category group)."""
    import json

    from .categories import preferences

    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        settings = preferences(database)
        removed = settings.setdefault("removed", {}).setdefault(kind, [])
        if name in removed:
            removed.remove(name)
        if kind == "category" and spending_class in ("Personal", "Fixed"):
            settings["classes"][name] = spending_class
        elif kind in ("account", "payment_method"):
            saved = settings.setdefault("choices", {}).setdefault(kind, [])
            if name not in saved:
                saved.append(name)
        connection.execute(
            "INSERT INTO category_settings(id,payload) VALUES(1,?) ON "
            "CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(settings, ensure_ascii=False),),
        )


def save_choice(
    database: Database, config: AppConfig, kind: str, name: str, *, source: str = ""
) -> int:
    """Add, rename or merge an account/method, preserving transaction identities."""
    import json
    from datetime import date

    from .categories import preferences
    from .models import TransactionDraft

    if kind not in ("account", "payment_method"):
        raise ValueError("Choose an account or payment method.")
    name = " ".join(name.split())
    if not name:
        raise ValueError("Enter a nonempty name.")
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        options = choice_options(database, config, kind)
        if source and source not in options:
            raise ValueError("This choice no longer exists. Reload and try again.")
        settings = preferences(database)
        aliases = settings.setdefault("choice_aliases", {}).setdefault(kind, {})
        # Reusing an old name makes it a real choice again, without alias cycles.
        aliases.pop(name, None)
        removed = settings.setdefault("removed", {}).setdefault(kind, [])
        if name in removed:
            removed.remove(name)
        saved = settings.setdefault("choices", {}).setdefault(kind, [])
        if name not in saved:
            saved.append(name)
        changed = 0
        if source and source != name:
            aliases.update({k: name for k, v in aliases.items() if v == source})
            aliases[source] = name
            if source not in removed:
                removed.append(source)
            if source in saved:
                saved.remove(source)
            for row in connection.execute(
                f"SELECT * FROM transactions WHERE {kind} = ?", (source,)
            ).fetchall():
                fields = {
                    key: row[key]
                    for key in (
                        "description",
                        "amount_cents",
                        "category",
                        "account",
                        "payment_method",
                        "merchant",
                        "transaction_type",
                        "notes",
                    )
                }
                fields[kind] = name
                draft = TransactionDraft(
                    transaction_date=date.fromisoformat(row["transaction_date"]), **fields
                ).validated()
                connection.execute(
                    f"UPDATE transactions SET {kind}=?, fingerprint=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (name, draft.fingerprint, row["id"]),
                )
                changed += 1
        connection.execute(
            "INSERT INTO category_settings(id,payload) VALUES(1,?) ON "
            "CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(settings, ensure_ascii=False),),
        )
    return changed


def delete_choice(
    database: Database, config: AppConfig, kind: str, source: str, *, replacement: str = ""
) -> None:
    """Remove unused vocabulary, or merge its references into a chosen replacement."""
    from .categories import effective_config, save_category

    config = effective_config(database, config)
    options = choice_options(database, config, kind)
    if source not in options or (kind == "category" and source == "Uncategorized"):
        raise ValueError("Select an editable choice.")
    if replacement:
        if replacement == source or replacement not in options:
            raise ValueError("Choose a different existing replacement.")
        if kind == "category":
            if replacement == "Uncategorized":
                raise ValueError("Choose a named replacement category.")
            save_category(
                database, config, replacement, config.spending_class(replacement), source=source
            )
        else:
            save_choice(database, config, kind, replacement, source=source)
    else:
        remove_unused_choices(database, config, kind, [source])
