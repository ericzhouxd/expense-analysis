"""Small local category registry and deterministic suggestion vocabulary."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from typing import Any

from .config import AppConfig
from .database import Database
from .models import TransactionDraft, normalize_text


def preferences(database: Database) -> dict:
    with database.connect() as connection:
        row = connection.execute("SELECT payload FROM category_settings WHERE id = 1").fetchone()
    return json.loads(row[0]) if row else {"classes": {}, "aliases": {}, "rules": {}}


def effective_config(database: Database, config: AppConfig) -> AppConfig:
    settings = preferences(database)
    classes = {
        **dict.fromkeys(config.personal_categories, "Personal"),
        **dict.fromkeys(config.fixed_categories, "Fixed"),
    }
    for category in database.list_transaction_categories():
        if category != "Uncategorized":
            classes.setdefault(category, "Personal")
    classes.update(settings["classes"])
    aliases = settings["aliases"]
    classes = {k: v for k, v in classes.items() if k not in aliases}
    rules = {**dict(config.category_rules), **settings["rules"]}
    return replace(
        config,
        personal_categories=tuple(k for k, v in classes.items() if v == "Personal"),
        fixed_categories=tuple(k for k, v in classes.items() if v == "Fixed"),
        category_rules=tuple((k, aliases.get(v, v)) for k, v in rules.items()),
        category_aliases=tuple(aliases.items()),
    )


def save_category(
    database: Database,
    config: AppConfig,
    name: str,
    spending_class: str,
    *,
    source: str = "",
    keyword: str = "",
) -> int:
    """Add/rename/merge atomically, including bill mappings and fingerprints."""
    name = " ".join(name.split())
    if not name or name == "Uncategorized" or spending_class not in ("Personal", "Fixed"):
        raise ValueError("Enter a category name and choose Personal or Fixed.")
    existing = effective_config(database, config).categories
    name = next((v for v in existing if v.casefold() == name.casefold()), name)
    settings = preferences(database)
    settings["classes"][name] = spending_class
    changed = 0
    plan = database.get_spending_plan()
    if source and source != name:
        if source == "Uncategorized":
            raise ValueError("Uncategorized is reserved; correct those transactions individually.")
        if source not in existing:
            raise ValueError("The source category no longer exists. Reload and try again.")
        settings["aliases"] = {
            k: name if v == source else v for k, v in settings["aliases"].items()
        }
        settings["aliases"][source] = name
        settings["classes"].pop(source, None)
        settings["rules"] = {k: name if v == source else v for k, v in settings["rules"].items()}
        if plan:
            plan = replace(
                plan,
                commitments=tuple(
                    replace(
                        c,
                        categories=tuple(
                            dict.fromkeys(name if v == source else v for v in c.categories)
                        ),
                    )
                    for c in plan.commitments
                ),
            )
            plan.validate()  # Reject merges that would make bill mappings overlap.
    if keyword.strip():
        settings["rules"][normalize_text(keyword)] = name
    with database.connect() as connection:
        if source and source != name:
            for row in connection.execute(
                "SELECT * FROM transactions WHERE category = ?", (source,)
            ).fetchall():
                draft = TransactionDraft(
                    **{
                        key: row[key]
                        for key in (
                            "description",
                            "amount_cents",
                            "account",
                            "payment_method",
                            "merchant",
                            "transaction_type",
                            "notes",
                        )
                    },
                    transaction_date=date.fromisoformat(row["transaction_date"]),
                    category=name,
                )
                connection.execute(
                    "UPDATE transactions SET category=?, fingerprint=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (name, draft.fingerprint, row["id"]),
                )
                changed += 1
            if plan:
                connection.execute(
                    "UPDATE spending_plans SET payload=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
                    (json.dumps(plan.to_dict(), ensure_ascii=False),),
                )
        connection.execute(
            "INSERT INTO category_settings(id,payload) VALUES(1,?) ON "
            "CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(settings, ensure_ascii=False),),
        )
    return changed


def suggestion_data(database: Database, config: AppConfig) -> dict[str, Any]:
    """Send only a compact vocabulary to the local entry component, never the ledger."""
    groups: dict[str, Counter] = defaultdict(Counter)
    for row in database.list_transactions():
        merchant = normalize_text(str(row["merchant"]))
        category = str(row["category"])
        if merchant and category in config.categories and category != "Uncategorized":
            groups[merchant][category] += 1
    merchants = {}
    for merchant, counts in groups.items():
        category, count = counts.most_common(1)[0]
        if count >= 2 and count / counts.total() >= 0.8:
            merchants[merchant] = category
    starter = {
        "grocer": "Food",
        "supermarket": "Food",
        "coffee": "Dining Out",
        "restaurant": "Dining Out",
        "rent": "Rent",
        "tuition": "Tuition",
        "pharmacy": "Medicine",
        "uber": "Transportation",
        "bus": "Transportation",
    }
    rules = {k: v for k, v in starter.items() if v in config.categories}
    rules.update(dict(config.category_rules))
    return {
        "categories": list(config.categories),
        "rules": list(rules.items()),
        "merchants": merchants,
    }
