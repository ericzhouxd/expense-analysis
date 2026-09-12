"""The Import / Export page."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from ..config import AppConfig
from ..database import Database
from ..import_export import CsvDecodeError, ImportPreview, export_csv, preview_csv
from .state import _invalidate_activity_filters
from .widgets import _page_heading, _section_heading


def _preview_table(preview: ImportPreview) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for row in preview.rows:
        draft = row.draft
        records.append(
            {
                "Row": row.row_number,
                "Status": ("Invalid" if row.errors else "Duplicate" if row.duplicate else "Ready"),
                "Date": draft.transaction_date if draft else None,
                "Description": draft.description if draft else "",
                "Amount": draft.amount_cents / 100 if draft else None,
                "Category": draft.category if draft else "",
                "Type": draft.transaction_type if draft else "",
                "Issue": "; ".join(row.errors),
            }
        )
    return pd.DataFrame(records)


def _render_csv_preview(database: Database, content: bytes, config: AppConfig) -> None:
    try:
        preview = preview_csv(content, config, database.existing_fingerprints())
    except CsvDecodeError as exc:
        st.error(str(exc))
        return
    ready = len(preview.valid_drafts)
    first, second, third = st.columns(3)
    first.metric("Ready", ready)
    second.metric("Duplicates", preview.duplicate_count)
    third.metric("Invalid", preview.invalid_count)
    st.dataframe(
        _preview_table(preview),
        hide_index=True,
        width="stretch",
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    if st.button(
        f"Import {ready} valid transaction(s)",
        type="primary",
        disabled=ready == 0,
    ):
        result = database.import_transactions(preview.valid_drafts)
        _invalidate_activity_filters()
        st.success(f"Imported {result.imported}; skipped {result.duplicates_skipped} duplicate(s).")
        st.rerun()


def _render_import_export(
    database: Database, rows: list[dict[str, object]], config: AppConfig
) -> None:
    _page_heading(
        "LOCAL FILES",
        "Import and export",
        "Bring in statements or create a private backup without leaving this computer.",
    )
    st.html(
        """
        <div class="privacy-strip">
            <span class="privacy-dot"></span>
            Files are processed locally. Nothing is uploaded to a remote service.
        </div>
        """
    )

    _section_heading("Import a CSV", "Review every row before it is saved")
    uploaded = st.file_uploader("Choose a CSV", type=["csv"])
    import_bytes: bytes | None = uploaded.getvalue() if uploaded else None

    if import_bytes:
        _render_csv_preview(database, import_bytes, config)

    st.divider()
    _section_heading("Export a local backup", "Keep the downloaded file secure")
    st.caption("The exported CSV contains private spending data. Store it securely.")
    st.download_button(
        "Download transactions.csv",
        data=export_csv(rows),
        file_name=f"expenses-{date.today().isoformat()}.csv",
        mime="text/csv",
        disabled=not rows,
    )
