"""The Transactions page and its add / review dialogs."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date

import pandas as pd
import streamlit as st

from ..analytics import (
    transactions_frame,
)
from ..choices import choice_options
from ..config import AppConfig
from ..database import Database, DuplicateTransactionError
from ..models import TransactionDraft, parse_amount_cents, validate_transaction_date
from ..transaction_edits import TransactionChange, apply_changes, collect_changes
from .state import (
    _category_options,
    _get_transaction,
    _invalidate_activity_filters,
    _reset_transaction_editor,
)
from .widgets import _currency, _page_heading, _transaction_list

# Glide renders a fixed 35px row under roughly 48px of header and toolbar, so a
# constant height either leaves blank space or pushes the actions off-screen.
_EDITOR_ROW_HEIGHT = 35
_EDITOR_CHROME_HEIGHT = 48


def _editor_height(row_count: int) -> int:
    return max(200, min(520, _EDITOR_CHROME_HEIGHT + _EDITOR_ROW_HEIGHT * row_count))


def _reveal_saved_transaction(transaction_id: str) -> None:
    """Widget callbacks run before the script, so the view switcher can be reset."""
    st.session_state["focused_transaction_id"] = transaction_id
    st.session_state["show_saved_transaction_notice"] = False
    st.session_state["transaction_view"] = "List"


@st.dialog("Review transaction changes", width="large")
def _review_transaction_changes(database: Database, changes: list[TransactionChange]) -> None:
    deletions = sum(change.after is None for change in changes)
    st.write(f"{len(changes) - deletions} transaction(s) edited · {deletions} marked for deletion")
    preview = []
    for change in changes:
        if change.after is None:
            preview.append(
                {
                    "Transaction": change.before.description,
                    "Field": "Delete transaction",
                    "Before": f"{change.before.transaction_date} · "
                    f"{_currency(change.before.amount_cents / 100)}",
                    "After": "Permanently deleted",
                }
            )
            continue
        for field, before in asdict(change.before).items():
            after = getattr(change.after, field)
            if before != after:
                preview.append(
                    {
                        "Transaction": change.before.description,
                        "Field": field.replace("_", " ").replace("amount cents", "amount").title(),
                        "Before": _currency(before / 100)
                        if field == "amount_cents"
                        else str(before),
                        "After": _currency(after / 100) if field == "amount_cents" else str(after),
                    }
                )
    st.dataframe(pd.DataFrame(preview), hide_index=True, width="stretch")
    st.caption("Close this review to keep editing. Nothing is saved until you confirm.")
    confirmed = not deletions or st.checkbox("I understand that these deletions are permanent.")
    if st.button("Confirm changes", type="primary", disabled=not confirmed):
        try:
            apply_changes(database, changes)
        except ValueError as exc:
            st.error(str(exc))
        except sqlite3.Error:
            st.error("Nothing was saved. The database could not complete the changes. Try again.")
        else:
            _reset_transaction_editor()
            st.session_state["transaction_editor_saved"] = len(changes)
            st.rerun()


def _render_transactions(database: Database, frame: pd.DataFrame, config: AppConfig) -> None:
    focused_transaction_id = st.session_state.get("focused_transaction_id")
    if focused_transaction_id:
        focused_row = _get_transaction(database, focused_transaction_id)
        if focused_row:
            focused_frame = transactions_frame([focused_row], config)
            frame = (
                pd.concat([focused_frame, frame], ignore_index=True)
                .drop_duplicates(subset="id", keep="first")
                .reset_index(drop=True)
            )

    heading, view_control, add_action = st.columns(
        (4, 1.1, 1.1), vertical_alignment="bottom", gap="large"
    )
    with heading:
        _page_heading(
            "ACTIVITY",
            "Transactions",
            "Browse comfortably or switch to the editing table when you need it.",
        )
    with view_control:
        view = (
            st.segmented_control(
                "Transaction view",
                ["List", "Edit table"],
                default="List",
                label_visibility="collapsed",
                key="transaction_view",
            )
            if not frame.empty
            else "List"
        )
    with add_action:
        if st.button(
            "Add transaction",
            type="primary",
            key="open_add_transaction",
            width="stretch",
        ):
            _add_transaction_dialog(database, config)

    saved_transaction_id = st.session_state.get("saved_transaction_id")
    if saved_transaction_id and st.session_state.get("show_saved_transaction_notice"):
        _, notice_column = st.columns((4, 2))
        with (
            notice_column,
            st.container(
                border=True,
                key="saved_transaction_notice",
                horizontal=True,
                horizontal_alignment="right",
                vertical_alignment="center",
                gap="small",
            ),
        ):
            st.markdown("**Transaction saved.**")
            st.button(
                "View",
                key="view_saved_transaction",
                type="tertiary",
                on_click=_reveal_saved_transaction,
                args=(saved_transaction_id,),
            )

    if frame.empty:
        st.info("No transactions match the current filters.")
        return
    if view == "List":
        _transaction_list(frame, focused_transaction_id=focused_transaction_id)
        return

    if saved_count := st.session_state.pop("transaction_editor_saved", None):
        st.success(f"Saved changes to {saved_count} transaction(s).")
    st.caption("Edit cells, then review the changes. Deletions require explicit confirmation.")
    editor_frame = pd.DataFrame(
        {
            "Delete": False,
            "ID": frame["id"],
            "Date": frame["transaction_date"].dt.date,
            "Description": frame["description"],
            "Amount": frame["amount"],
            "Category": frame["category"],
            "Account": frame["account"],
            "Payment method": frame["payment_method"],
            "Merchant": frame["merchant"],
            "Type": frame["transaction_type"],
            "Notes": frame["notes"],
        }
    )
    baseline = st.session_state.get("transaction_editor_baseline")
    if baseline is None or tuple(baseline["ID"]) != tuple(editor_frame["ID"]):
        _reset_transaction_editor()
        st.session_state["transaction_editor_baseline"] = editor_frame.copy(deep=True)
    editor_frame = st.session_state["transaction_editor_baseline"]
    choice_columns = {
        "Category": "category",
        "Account": "account",
        "Payment method": "payment_method",
    }
    display_frame = editor_frame.copy(deep=True)
    for column in choice_columns:
        display_frame[column] = display_frame[column].map(lambda value: [value] if value else [])
    edited = st.data_editor(
        display_frame,
        hide_index=True,
        width="stretch",
        height=_editor_height(len(editor_frame)),
        disabled=["ID"],
        column_config={
            "Delete": st.column_config.CheckboxColumn("Delete"),
            "ID": None,
            "Description": st.column_config.TextColumn("Description", required=True),
            "Date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
            "Amount": st.column_config.NumberColumn(
                "Amount", min_value=0.01, step=0.01, format="$%.2f", required=True
            ),
            **{
                column: st.column_config.MultiselectColumn(
                    column,
                    options=choice_options(database, config, kind),
                    accept_new_options=True,
                    required=column == "Category",
                    help="Remove the current choice to replace it. "
                    "Type a new value and press Enter to confirm it.",
                )
                for column, kind in choice_columns.items()
            },
            "Type": st.column_config.SelectboxColumn(
                "Type",
                options=["expense", "refund", "income", "transfer"],
                required=True,
            ),
        },
        key=f"transaction_editor_{st.session_state.get('transaction_editor_generation', 0)}",
    )
    changes = []
    try:
        changes = collect_changes(display_frame, edited)
    except ValueError as exc:
        st.error(str(exc))
    _, review_column, discard_column = st.columns((4, 1.3, 1.3), vertical_alignment="center")
    if review_column.button(
        f"Review changes ({len(changes)})",
        type="primary",
        disabled=not changes,
        width="stretch",
    ):
        _review_transaction_changes(database, changes)
    if discard_column.button("Discard edits / reload", width="stretch"):
        _reset_transaction_editor()
        st.rerun()


@st.dialog("Add a transaction", width="large")
def _add_transaction_dialog(database: Database, config: AppConfig) -> None:
    st.caption("Description and amount are required.")
    with st.form("add_transaction_form", clear_on_submit=True):
        left, right = st.columns(2)
        transaction_date_text = left.text_input(
            "Date",
            value=date.today().isoformat(),
            placeholder="YYYY-MM-DD",
            key="add_transaction_date",
        )
        transaction_type = right.selectbox(
            "Type",
            ["expense", "refund", "income", "transfer"],
            key="add_transaction_type",
        )
        description = st.text_input(
            "Description",
            placeholder="What was this for?",
            key="add_transaction_description",
        )
        merchant = st.text_input(
            "Merchant",
            placeholder="Optional, improves recurring analysis",
            key="add_transaction_merchant",
        )
        left, right = st.columns(2)
        amount = left.number_input(
            "Amount",
            min_value=0.01,
            value=None,
            step=0.01,
            format="%.2f",
            placeholder="0.00",
            key="add_transaction_amount",
        )
        category = right.selectbox(
            "Category",
            _category_options(database, config),
            key="add_transaction_category",
            accept_new_options=True,
        )
        left, right = st.columns(2)
        account = left.selectbox(
            "Account",
            choice_options(database, config, "account"),
            index=(
                config.accounts.index(config.default_account)
                if config.default_account in config.accounts
                else 0
            ),
            key="add_transaction_account",
            accept_new_options=True,
        )
        payment_method = right.selectbox(
            "Payment method",
            choice_options(database, config, "payment_method"),
            index=(
                config.payment_methods.index(config.default_payment_method)
                if config.default_payment_method in config.payment_methods
                else 0
            ),
            key="add_transaction_payment_method",
            accept_new_options=True,
        )
        notes = st.text_area("Notes", height=80, key="add_transaction_notes")
        submitted = st.form_submit_button(
            "Save transaction",
            type="primary",
            key="add_transaction_submit",
        )
    if submitted:
        try:
            transaction_date = validate_transaction_date(transaction_date_text)
        except ValueError as exc:
            st.error(str(exc))
        else:
            try:
                transaction_id = database.add_transaction(
                    TransactionDraft(
                        transaction_date=transaction_date,
                        description=description,
                        amount_cents=parse_amount_cents(amount),
                        category=category,
                        account=account,
                        payment_method=payment_method,
                        merchant=merchant,
                        transaction_type=transaction_type,
                        notes=notes,
                    )
                )
            except (ValueError, DuplicateTransactionError) as exc:
                st.error(str(exc))
            else:
                _invalidate_activity_filters()
                st.session_state["saved_transaction_id"] = transaction_id
                st.session_state["show_saved_transaction_notice"] = True
                st.rerun()
