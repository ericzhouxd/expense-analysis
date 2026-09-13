"""The Settings page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import DATABASE_PATH, AppConfig
from ..database import Database
from .widgets import _page_heading, _section_heading


def _render_settings(database: Database, config: AppConfig) -> None:
    _page_heading(
        "PREFERENCES",
        "Settings and privacy",
        "Your data stays local, and your personal choices stay configurable.",
    )
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
    _section_heading("Local configuration", "Private defaults and calendar rules")
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
