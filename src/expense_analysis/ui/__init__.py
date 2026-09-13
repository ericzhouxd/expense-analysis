"""Streamlit pages for the local ledger.

Each page lives in its own module. ``render_app`` stays here, next to the
``_database`` and ``load_config`` names it reads at call time, so tests can keep
replacing either through this module.
"""

from __future__ import annotations

import streamlit as st

from ..config import load_config
from ..database import Database
from ..presentation import inject_theme
from .budgets import _render_budgets as _render_budgets
from .dashboard import _render_dashboard as _render_dashboard
from .import_export import (
    _preview_table as _preview_table,
)
from .import_export import (
    _render_import_export as _render_import_export,
)
from .insights import _render_insights as _render_insights
from .settings import _render_settings as _render_settings
from .state import (
    _ACTIVITY_FILTER_GENERATION as _ACTIVITY_FILTER_GENERATION,
)
from .state import (
    _ACTIVITY_FILTER_SIGNATURE as _ACTIVITY_FILTER_SIGNATURE,
)
from .state import (
    _category_options as _category_options,
)
from .state import (
    _clear_focused_transaction as _clear_focused_transaction,
)
from .state import (
    _filtered_data as _filtered_data,
)
from .state import (
    _get_transaction as _get_transaction,
)
from .state import (
    _invalidate_activity_filters as _invalidate_activity_filters,
)
from .state import (
    _render_empty_state as _render_empty_state,
)
from .state import (
    _reset_transaction_editor as _reset_transaction_editor,
)
from .theme import PLOTLY_CONFIG as PLOTLY_CONFIG
from .transactions import (
    _add_transaction_dialog as _add_transaction_dialog,
)
from .transactions import (
    _render_transactions as _render_transactions,
)
from .transactions import (
    _review_transaction_changes as _review_transaction_changes,
)
from .widgets import (
    _currency as _currency,
)
from .widgets import (
    _kpi_card as _kpi_card,
)
from .widgets import (
    _kpi_card_markup as _kpi_card_markup,
)
from .widgets import (
    _page_heading as _page_heading,
)
from .widgets import (
    _percent_delta as _percent_delta,
)
from .widgets import (
    _plotly_chart as _plotly_chart,
)
from .widgets import (
    _safe_inline as _safe_inline,
)
from .widgets import (
    _section_heading as _section_heading,
)
from .widgets import (
    _style_figure as _style_figure,
)
from .widgets import (
    _transaction_list as _transaction_list,
)
from .widgets import (
    _transaction_list_markup as _transaction_list_markup,
)


@st.cache_resource
def _database() -> Database:
    """Open the local database and initialize schema v2 (student spending plans)."""
    database = Database()
    database.initialize()
    return database


def _inject_styles() -> None:
    inject_theme()


def render_app() -> None:
    st.set_page_config(
        page_title="記帳",
        page_icon="▦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles()
    database = _database()
    config = load_config()

    st.html('<header class="masthead"><span class="wordmark" lang="zh-Hant">記帳</span></header>')

    page = st.sidebar.radio(
        "Navigate",
        [
            "Overview",
            "Transactions",
            "Import / Export",
            "Budgets",
            "Advanced insights",
            "Settings",
        ],
        label_visibility="collapsed",
        key="main_navigation",
    )
    st.sidebar.divider()
    with st.sidebar:
        st.html(
            """
            <div class="theme-control">
                <span class="theme-control-label">Appearance</span>
                <div class="theme-options" role="radiogroup" aria-label="Appearance">
                    <button type="button" role="radio" aria-checked="true"
                        data-jizhang-theme-choice="System">System</button>
                    <button type="button" role="radio" aria-checked="false"
                        data-jizhang-theme-choice="Light">Light</button>
                    <button type="button" role="radio" aria-checked="false"
                        data-jizhang-theme-choice="Dark">Dark</button>
                </div>
            </div>
            """
        )

    if page == "Budgets":
        _render_budgets(database, config)
        return
    if page == "Settings":
        _render_settings(database, config)
        return

    all_rows, rows, frame = _filtered_data(database, config)
    if page == "Overview":
        _render_dashboard(database, frame, all_rows)
    elif page == "Transactions":
        _render_transactions(database, frame, config)
    elif page == "Import / Export":
        _render_import_export(database, rows, config)
    elif page == "Advanced insights":
        _render_insights(database, frame)
