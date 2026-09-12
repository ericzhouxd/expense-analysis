"""The Budgets page."""

from __future__ import annotations

from ..budget_ui import render_budget_page
from ..config import AppConfig
from ..database import Database
from .widgets import _page_heading


def _render_budgets(database: Database, config: AppConfig) -> None:
    _page_heading(
        "YOUR SPENDING PLAN",
        "Budgets",
        "Monthly and quarterly allowance after committed costs.",
    )
    render_budget_page(database, config)
