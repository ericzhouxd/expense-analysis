"""Local, form-buffered entry fields with browser-side category suggestions."""

from pathlib import Path

import streamlit as st

from .categories import suggestion_data
from .config import AppConfig
from .database import Database


def category_entry(database: Database, config: AppConfig) -> dict:
    assets = Path(__file__).parent / "assets"
    component = st.components.v2.component(
        "expense_category_entry",
        html=(assets / "category_entry.html").read_text(),
        css=(assets / "category_entry.css").read_text(),
        js=(assets / "category_entry.js").read_text(),
        isolate_styles=False,
    )
    initial = st.session_state.get("transaction_entry", {}).get(
        "entry", {"description": "", "merchant": "", "category": "Uncategorized", "manual": False}
    )
    result = component(
        data={**suggestion_data(database, config), "initial": initial},
        default={"entry": initial},
        key="transaction_entry",
        on_entry_change=lambda: None,
    )
    return dict(result.entry or initial)
