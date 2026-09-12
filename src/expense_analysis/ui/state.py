"""Session state, the activity filters, and the small data lookups."""

from __future__ import annotations

from datetime import date
from typing import cast

import pandas as pd
import streamlit as st

from ..analytics import (
    transactions_frame,
)
from ..choices import choice_options
from ..config import AppConfig
from ..database import Database

_ACTIVITY_FILTER_GENERATION = "activity_filter_generation"


_ACTIVITY_FILTER_SIGNATURE = "activity_filter_signature"


def _render_empty_state() -> None:
    st.html(
        """
        <div class="empty-card">
            <h2>No transactions yet</h2>
            <p>
                Add a transaction or import a CSV. Everything is stored
                in a local SQLite database and stays on this computer.
            </p>
        </div>
        """
    )


def _invalidate_activity_filters() -> None:
    """Rebuild the sidebar activity filters with their defaults on the next run.

    The dashboard and insights honour the activity filters, so a filter left over
    from before a transaction is added or imported can keep the new data out of the
    analysis. Bumping the generation recreates the widgets instead of restoring the
    stale selection.
    """
    st.session_state[_ACTIVITY_FILTER_GENERATION] = (
        st.session_state.get(_ACTIVITY_FILTER_GENERATION, 0) + 1
    )


def _clear_focused_transaction() -> None:
    """Drop a saved-transaction highlight once the activity filters change.

    The "View" confirmation intentionally reveals a new transaction even when the
    active filters exclude it. The highlight is a one-off reveal, so the first
    filter edit should return the list to the filtered selection.
    """
    st.session_state.pop("focused_transaction_id", None)


def _filtered_data(
    database: Database, config: AppConfig
) -> tuple[list[dict[str, object]], list[dict[str, object]], pd.DataFrame]:
    all_rows = database.list_transactions()
    all_frame = transactions_frame(all_rows, config)
    if all_frame.empty:
        return all_rows, all_rows, all_frame

    minimum = all_frame["transaction_date"].min().date()
    maximum = all_frame["transaction_date"].max().date()
    category_options = choice_options(database, config, "category")
    account_options = choice_options(database, config, "account")
    # Recreate the filters when the ledger range or its choice lists change, matching the
    # previous behaviour of dropping options that no longer exist.
    signature = (minimum, maximum, tuple(category_options), tuple(account_options))
    if st.session_state.get(_ACTIVITY_FILTER_SIGNATURE) != signature:
        st.session_state[_ACTIVITY_FILTER_SIGNATURE] = signature
        _invalidate_activity_filters()
    filter_generation = st.session_state.get(_ACTIVITY_FILTER_GENERATION, 0)
    with st.sidebar.expander("Filter activity", expanded=False):
        selected_range = st.date_input(
            "Date range",
            value=(minimum, maximum),
            min_value=minimum,
            max_value=max(maximum, date.today()),
            key=f"activity_date_range_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        if isinstance(selected_range, tuple) and len(selected_range) == 2:
            start, end = selected_range
        else:
            start, end = minimum, maximum
        search = st.text_input(
            "Search",
            placeholder="Description, merchant, notes…",
            key=f"activity_search_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        selected_categories = st.multiselect(
            "Categories",
            category_options,
            placeholder="All categories",
            accept_new_options=True,
            key=f"activity_categories_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        selected_types = st.multiselect(
            "Transaction types",
            ["expense", "refund", "income", "transfer"],
            placeholder="All types",
            key=f"activity_types_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
        selected_accounts = st.multiselect(
            "Accounts",
            account_options,
            placeholder="All accounts",
            accept_new_options=True,
            key=f"activity_accounts_{filter_generation}",
            on_change=_clear_focused_transaction,
        )
    if (
        start == minimum
        and end == maximum
        and not search.strip()
        and not selected_categories
        and not selected_types
        and not selected_accounts
    ):
        return all_rows, all_rows, all_frame
    rows = database.list_transactions(
        start=start,
        end=end,
        categories=selected_categories,
        transaction_types=selected_types,
        accounts=selected_accounts,
        search=search,
    )
    return all_rows, rows, transactions_frame(rows, config)


def _category_options(database: Database, config: AppConfig) -> list[str]:
    return choice_options(database, config, "category")


def _get_transaction(database: Database, transaction_id: str) -> dict[str, object] | None:
    transaction_reader = getattr(database, "get_transaction", None)
    if transaction_reader is not None:
        return cast("dict[str, object] | None", transaction_reader(transaction_id))
    return next(
        (row for row in database.list_transactions() if str(row.get("id", "")) == transaction_id),
        None,
    )


def _reset_transaction_editor() -> None:
    st.session_state.pop("transaction_editor_baseline", None)
    st.session_state["transaction_editor_generation"] = (
        st.session_state.get("transaction_editor_generation", 0) + 1
    )
