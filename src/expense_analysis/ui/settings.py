"""The Settings page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..categories import save_category
from ..choices import choice_options, remove_unused_choices, unused_choices
from ..config import DATABASE_PATH, AppConfig
from ..database import Database
from .widgets import _page_heading, _section


def _render_settings(database: Database, config: AppConfig) -> None:
    _page_heading(
        "PREFERENCES",
        "Settings and privacy",
        "Your data stays local, and your personal choices stay configurable.",
    )
    with st.expander("Manage categories"):
        st.caption(
            "Keep broad categories; add exceptions when useful. Renaming also "
            "updates transactions and budget mappings."
        )
        options = [v for v in choice_options(database, config, "category") if v != "Uncategorized"]
        source = st.selectbox("Category to edit", ["Add a category", *options])
        current = "" if source == "Add a category" else source
        with st.form("manage_category"):
            name = st.text_input("Category name", value=current, key=f"category_name_{source}")
            group = st.selectbox(
                "Spending group",
                ["Personal", "Fixed"],
                index=int(config.spending_class(current) == "Fixed"),
                key=f"category_group_{source}",
            )
            keyword = st.text_input(
                "Auto-categorize when description or merchant contains",
                placeholder="Optional keyword or phrase",
            )
            if current:
                count = len(database.list_transactions(categories=[current]))
                st.caption(
                    f"{count} transaction(s) use this category. Enter an existing name "
                    f"to merge into it. Overlapping budget mappings will be rejected."
                )
            submitted = st.form_submit_button("Save category")
        if submitted:
            try:
                save_category(database, config, name, group, source=current, keyword=keyword)
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["category_saved"] = True
                st.rerun()
    if st.session_state.pop("category_saved", False):
        st.success("Category saved locally.")
    with st.expander("Remove unused categories, accounts and payment methods"):
        st.caption(
            "Only unused choices are listed. Transactions, planned bills, category rules "
            "and entry defaults are protected. Removed choices stay removed after restart."
        )
        for kind, label in (
            ("category", "Categories"),
            ("account", "Accounts"),
            ("payment_method", "Payment methods"),
        ):
            available = unused_choices(database, config, kind)
            selected = st.multiselect(label, available, key=f"cleanup_{kind}")
            if st.button(f"Remove selected {label.lower()}", disabled=not selected):
                try:
                    remove_unused_choices(database, config, kind, selected)
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.rerun()
    st.html(
        """
        <div class="privacy-hero">
            <span class="privacy-dot"></span>
            <div><strong>Local-only mode is active</strong>
            <span>The app is bound to this computer and telemetry is disabled.</span></div>
        </div>
        """
    )
    st.markdown(
        f"""
        - Database: `{DATABASE_PATH}`
        - Network binding: `127.0.0.1`
        - Streamlit telemetry: disabled
        - Private data and exports: ignored by Git
        - Transactions stored: `{database.count_transactions():,}`
        """
    )
    with _section(
        "local-configuration", "Local configuration", "Private defaults and calendar rules"
    ):
        st.write(
            "Copy `config.example.toml` to `config.toml` to customize categories, "
            "accounts, defaults, and the academic calendar. `config.toml` is ignored "
            "by Git, so personal account names remain local."
        )
        st.code("cp config.example.toml config.toml", language="bash")
        calendar_config = config.academic_calendar
        st.dataframe(
            pd.DataFrame(
                {
                    "Period": ["Fall", "Winter", "Spring", "Summer"],
                    "Months": [
                        ", ".join(map(str, calendar_config.fall_months)),
                        ", ".join(map(str, calendar_config.winter_months)),
                        ", ".join(map(str, calendar_config.spring_months)),
                        ", ".join(map(str, calendar_config.summer_months)),
                    ],
                }
            ),
            hide_index=True,
            width="stretch",
        )
        if calendar_config.explicit_periods:
            st.caption("Explicit date ranges override the month-based fallback:")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Label": period.label,
                            "Start": period.start,
                            "End": period.end,
                        }
                        for period in calendar_config.explicit_periods
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
