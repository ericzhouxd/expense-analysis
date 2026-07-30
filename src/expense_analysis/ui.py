from __future__ import annotations

import html
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .analytics import (
    academic_period_spending,
    budget_status,
    cash_flow_by_month,
    category_spending,
    comparable_year_months,
    monthly_spending,
    period_metrics,
    recurring_transactions,
    savings_summary,
    spending_anomalies,
    spending_drivers,
    transactions_frame,
)
from .config import DATABASE_PATH, AppConfig, load_config
from .database import Database, DuplicateTransactionError
from .import_export import ImportPreview, export_csv, preview_csv
from .models import TransactionDraft, parse_amount_cents

PRIMARY = "#3D6B57"
PRIMARY_DARK = "#254C3D"
SAGE = "#A9C3B3"
MINT = "#DDEBE3"
GOLD = "#C59A4A"
CORAL = "#C9685D"
INK = "#1F2A24"
MUTED = "#6F7C74"
GRID = "#E5E8E3"
PALETTE = (
    PRIMARY,
    GOLD,
    "#718E7E",
    "#9F7A66",
    "#758DA3",
    "#9B8AAD",
    "#7F9972",
    CORAL,
    "#A39A78",
    "#8A928C",
)


def _currency(value: float) -> str:
    prefix = "-$" if value < 0 else "$"
    return f"{prefix}{abs(value):,.2f}"


def _percent_delta(value: float | None) -> str | None:
    return None if value is None else f"{value:+.1f}%"


def _style_figure(figure: go.Figure, *, height: int = 380) -> go.Figure:
    figure.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 16, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, -apple-system, BlinkMacSystemFont, sans-serif"},
        font_color=INK,
        legend_title_text="",
        hoverlabel={"bgcolor": "white", "bordercolor": GRID, "font_color": INK},
        colorway=PALETTE,
    )
    figure.update_xaxes(showgrid=False)
    figure.update_yaxes(gridcolor=GRID, zeroline=False)
    return figure


def _page_heading(kicker: str, title: str, description: str = "") -> None:
    description_html = (
        f'<p class="page-description">{html.escape(description)}</p>' if description else ""
    )
    st.html(
        f"""
        <div class="page-heading">
            <div class="page-kicker">{html.escape(kicker)}</div>
            <h1>{html.escape(title)}</h1>
            {description_html}
        </div>
        """
    )


def _kpi_card(
    label: str,
    value: str,
    *,
    detail: str = "",
    change: float | None = None,
    featured: bool = False,
) -> None:
    if change is None:
        change_html = ""
    else:
        change_class = "calm" if change <= 0 else "attention"
        arrow = "↓" if change < 0 else "↑" if change > 0 else "→"
        change_html = f'<span class="kpi-change {change_class}">{arrow} {abs(change):.1f}%</span>'
    card_class = "kpi-card featured" if featured else "kpi-card"
    st.html(
        f"""
        <div class="{card_class}">
            <div class="kpi-label">{html.escape(label)}</div>
            <div class="kpi-value">{html.escape(value)}</div>
            <div class="kpi-foot">{change_html}<span>{html.escape(detail)}</span></div>
        </div>
        """
    )


def _section_heading(title: str, description: str = "") -> None:
    description_html = f"<span>{html.escape(description)}</span>" if description else ""
    st.html(f'<div class="section-heading"><h2>{html.escape(title)}</h2>{description_html}</div>')


def _safe_inline(value: object) -> str:
    return html.escape(" ".join(str(value).split()))


def _transaction_list_markup(frame: pd.DataFrame, *, limit: int | None = None) -> str:
    display = frame.sort_values("transaction_date", ascending=False)
    if limit:
        display = display.head(limit)
    rows: list[str] = []
    for _, item in display.iterrows():
        transaction_type = str(item["transaction_type"])
        amount = float(item["amount"])
        if transaction_type == "expense":
            amount_text = f"−{_currency(amount)}"
            amount_class = "expense"
        elif transaction_type in {"income", "refund"}:
            amount_text = f"+{_currency(amount)}"
            amount_class = "income"
        else:
            amount_text = _currency(amount)
            amount_class = "transfer"
        merchant = str(item["merchant"]).strip()
        title = merchant or str(item["description"])
        description = (
            str(item["description"]) if merchant and merchant != item["description"] else ""
        )
        details = " · ".join(
            value
            for value in (
                str(item["category"]),
                str(item["account"]).strip(),
                pd.Timestamp(item["transaction_date"]).strftime("%b %d").replace(" 0", " "),
            )
            if value
        )
        secondary = (
            f'<div class="transaction-note">{_safe_inline(description)}</div>'
            if description
            else ""
        )
        rows.append(
            f'<div class="transaction-row">'
            f'<div class="transaction-main">'
            f'<div class="transaction-title">{_safe_inline(title)}</div>'
            f"{secondary}"
            f'<div class="transaction-meta">{_safe_inline(details)}</div>'
            f"</div>"
            f'<div class="transaction-amount {amount_class}">'
            f"{_safe_inline(amount_text)}"
            f"</div>"
            f"</div>"
        )
    return f'<div class="transaction-list">{"".join(rows)}</div>'


def _transaction_list(frame: pd.DataFrame, *, limit: int | None = None) -> None:
    st.html(_transaction_list_markup(frame, limit=limit))


@st.cache_resource
def _database() -> Database:
    database = Database()
    database.initialize()
    return database


def _render_empty_state() -> None:
    st.html(
        """
        <div class="empty-card">
            <div class="eyebrow">LOCAL-FIRST BY DESIGN</div>
            <h2>Your private spending workspace is ready.</h2>
            <p>
                Add a transaction or import a CSV. Everything is stored
                in a local SQLite database and stays on this computer.
            </p>
        </div>
        """
    )


def _filtered_data(
    database: Database, config: AppConfig
) -> tuple[list[dict[str, object]], pd.DataFrame]:
    all_rows = database.list_transactions()
    all_frame = transactions_frame(all_rows, config)
    if all_frame.empty:
        return all_rows, all_frame

    minimum = all_frame["transaction_date"].min().date()
    maximum = all_frame["transaction_date"].max().date()
    category_options = sorted(all_frame["category"].dropna().unique())
    account_options = sorted(value for value in all_frame["account"].dropna().unique() if value)
    with st.sidebar.expander("Filter activity", expanded=False):
        selected_range = st.date_input(
            "Date range",
            value=(minimum, maximum),
            min_value=minimum,
            max_value=max(maximum, date.today()),
        )
        if isinstance(selected_range, tuple) and len(selected_range) == 2:
            start, end = selected_range
        else:
            start, end = minimum, maximum
        search = st.text_input("Search", placeholder="Description, merchant, notes…")
        selected_categories = st.multiselect(
            "Categories", category_options, placeholder="All categories"
        )
        selected_types = st.multiselect(
            "Transaction types",
            ["expense", "refund", "income", "transfer"],
            placeholder="All types",
        )
        selected_accounts = st.multiselect("Accounts", account_options, placeholder="All accounts")
    rows = database.list_transactions(
        start=start,
        end=end,
        categories=selected_categories,
        transaction_types=selected_types,
        accounts=selected_accounts,
        search=search,
    )
    return rows, transactions_frame(rows, config)


def _render_dashboard(database: Database, frame: pd.DataFrame) -> None:
    _page_heading(
        "OVERVIEW",
        "Your spending, at a glance",
        "A calm view of what changed and where your money went.",
    )
    if frame.empty:
        _render_empty_state()
        return

    metrics = period_metrics(frame, personal_only=True)
    latest_month = str(frame["month"].max())
    budgets = budget_status(frame, database.get_budgets(latest_month), latest_month)
    budget_remaining = float(budgets["remaining"].sum()) if not budgets.empty else None
    period_detail = "Partial month" if metrics.is_partial else "Complete month"
    card1, card2, card3, card4 = st.columns(4)
    with card1:
        _kpi_card(
            "Personal spending",
            _currency(metrics.spending),
            detail=metrics.period_label,
            change=metrics.change_from_previous,
            featured=True,
        )
    with card2:
        _kpi_card(
            "Budget remaining",
            _currency(budget_remaining) if budget_remaining is not None else "Not set",
            detail="Across personal categories"
            if budget_remaining is not None
            else "Add a monthly plan",
        )
    with card3:
        _kpi_card(
            "Compared with last month",
            _percent_delta(metrics.change_from_previous) or "No baseline",
            detail="Through the same day" if metrics.is_partial else "Full month",
        )
    with card4:
        _kpi_card(
            "Month-end outlook",
            (
                _currency(metrics.projected_month_end)
                if metrics.is_partial
                else _currency(metrics.spending)
            ),
            detail=period_detail,
        )

    monthly = monthly_spending(frame, personal_only=True)
    personal_frame = frame[frame["spending_class"].eq("Personal")]
    drivers = spending_drivers(personal_frame)
    recurring = recurring_transactions(personal_frame)
    anomalies = spending_anomalies(personal_frame)

    if metrics.change_from_previous is None:
        trend_title = "Your monthly spending rhythm"
    elif metrics.change_from_previous > 0:
        trend_title = f"Spending rose {abs(metrics.change_from_previous):.0f}% from last month"
    else:
        trend_title = f"Spending eased {abs(metrics.change_from_previous):.0f}% from last month"

    left, right = st.columns((1.7, 1), gap="large")
    with left:
        _section_heading(
            trend_title,
            f"Three-month average: {_currency(metrics.monthly_average)}",
        )
        if monthly.empty:
            st.info("Add expense history to see trends.")
        else:
            trend = go.Figure()
            x_values = monthly["month"].dt.to_timestamp()
            trend.add_trace(
                go.Scatter(
                    x=x_values,
                    y=monthly["spending"],
                    name="Monthly spending",
                    mode="lines+markers",
                    line={"color": PRIMARY, "width": 2.5, "shape": "spline"},
                    marker={"size": 7, "color": PRIMARY, "line": {"width": 2, "color": "white"}},
                    fill="tozeroy",
                    fillcolor="rgba(61, 107, 87, 0.08)",
                    hovertemplate="%{x|%b %Y}<br>$%{y:,.2f}<extra></extra>",
                )
            )
            trend.add_trace(
                go.Scatter(
                    x=x_values,
                    y=monthly["rolling_3"],
                    name="3-month average",
                    mode="lines",
                    line={"color": GOLD, "width": 1.8, "dash": "dot"},
                    hovertemplate="%{x|%b %Y}<br>$%{y:,.2f}<extra></extra>",
                )
            )
            trend.update_yaxes(tickprefix="$", rangemode="tozero")
            st.plotly_chart(_style_figure(trend, height=360), width="stretch")

    with right:
        _section_heading("What changed", "The useful signals from this period")
        insight_rows: list[str] = []
        for _, driver in drivers.head(3).iterrows():
            change = float(driver["change"])
            if change == 0:
                continue
            direction = "added" if change > 0 else "fell by"
            tone = "attention" if change > 0 else "calm"
            insight_rows.append(
                f"""
                <div class="insight-row">
                    <span class="insight-dot {tone}"></span>
                    <div><strong>{html.escape(str(driver["category"]))}</strong>
                    {direction} {_currency(abs(change))}</div>
                </div>
                """
            )
        if not anomalies.empty:
            insight_rows.append(
                f"""
                <div class="insight-row">
                    <span class="insight-dot attention"></span>
                    <div><strong>{len(anomalies)} unusual purchase(s)</strong>
                    may be worth reviewing</div>
                </div>
                """
            )
        if not recurring.empty:
            insight_rows.append(
                f"""
                <div class="insight-row">
                    <span class="insight-dot neutral"></span>
                    <div><strong>{len(recurring)} recurring pattern(s)</strong>
                    detected in your history</div>
                </div>
                """
            )
        if not insight_rows:
            insight_rows.append(
                """
                <div class="insight-row">
                    <span class="insight-dot calm"></span>
                    <div><strong>Nothing unusual</strong>
                    Your recent spending looks steady</div>
                </div>
                """
            )
        st.html(f'<div class="insight-card">{"".join(insight_rows)}</div>')

    categories = category_spending(frame, personal_only=True)
    left, right = st.columns((1.15, 1), gap="large")
    with left:
        category_title = (
            f"{categories.iloc[0]['category']} is your largest category"
            if not categories.empty
            else "Where your money went"
        )
        _section_heading(category_title, "Personal spending in the selected range")
        if categories.empty:
            st.info("No personal expenses in the selected range.")
        else:
            category_chart = px.bar(
                categories.head(8).sort_values("spending"),
                x="spending",
                y="category",
                orientation="h",
                text_auto="$.3s",
                labels={"spending": "Spending", "category": ""},
            )
            category_chart.update_traces(
                marker_color=PRIMARY,
                marker_line_width=0,
                hovertemplate="<b>%{y}</b><br>$%{x:,.2f}<extra></extra>",
                textposition="outside",
                cliponaxis=False,
            )
            category_chart.update_layout(showlegend=False)
            category_chart.update_xaxes(visible=False)
            category_chart.update_yaxes(gridcolor="rgba(0,0,0,0)")
            st.plotly_chart(_style_figure(category_chart, height=340), width="stretch")

    with right:
        _section_heading(
            f"Budget progress · {latest_month}",
            "A quick read on your monthly plan",
        )
        if budgets.empty:
            st.html(
                """
                <div class="soft-empty">
                    <strong>No budget yet</strong>
                    <span>Set a few category limits to see progress here.</span>
                </div>
                """
            )
        else:
            budget_rows: list[str] = []
            for _, budget in budgets.head(6).iterrows():
                percent = float(budget["percent_used"])
                width = min(max(percent, 0), 100)
                remaining = _currency(float(budget["remaining"]))
                bar_class = "over" if percent > 100 else "near" if percent > 80 else ""
                budget_rows.append(
                    f"""
                    <div class="budget-row">
                        <div class="budget-label">
                            <strong>{html.escape(str(budget["category"]))}</strong>
                            <span>{percent:.0f}% · {remaining} left</span>
                        </div>
                        <div class="budget-track">
                            <div class="budget-fill {bar_class}" style="width:{width:.1f}%"></div>
                        </div>
                    </div>
                    """
                )
            st.html(f'<div class="budget-card">{"".join(budget_rows)}</div>')

    _section_heading("Recent activity", "Your latest local transactions")
    _transaction_list(frame, limit=6)

    with st.expander("Explore comparisons and spending mix"):
        class_totals = (
            frame[frame["transaction_type"].isin(["expense", "refund"])]
            .groupby("spending_class", as_index=False)["spending"]
            .sum()
        )
        year_months = comparable_year_months(frame)
        left, right = st.columns(2)
        with left:
            st.markdown("#### Like-for-like monthly view")
            if not year_months.empty:
                comparison = px.bar(
                    year_months,
                    x="month_number",
                    y="spending",
                    color=year_months["year"].astype(str),
                    barmode="group",
                    labels={
                        "month_number": "Month",
                        "spending": "Spending",
                        "color": "Year",
                    },
                    color_discrete_sequence=(PRIMARY, SAGE, GOLD, CORAL),
                )
                comparison.update_xaxes(
                    tickmode="array",
                    tickvals=list(range(1, 13)),
                    ticktext=[
                        "Jan",
                        "Feb",
                        "Mar",
                        "Apr",
                        "May",
                        "Jun",
                        "Jul",
                        "Aug",
                        "Sep",
                        "Oct",
                        "Nov",
                        "Dec",
                    ],
                )
                comparison.update_yaxes(tickprefix="$")
                st.plotly_chart(_style_figure(comparison, height=300), width="stretch")
        with right:
            st.markdown("#### Fixed and personal spending")
            if not class_totals.empty:
                mix = px.bar(
                    class_totals,
                    x="spending",
                    y=["Total"] * len(class_totals),
                    color="spending_class",
                    orientation="h",
                    text_auto="$.3s",
                    color_discrete_map={
                        "Personal": PRIMARY,
                        "Fixed": GOLD,
                        "Uncategorized": "#A3AAA5",
                    },
                    labels={"spending": "Spending", "spending_class": ""},
                )
                mix.update_yaxes(visible=False)
                mix.update_xaxes(visible=False)
                st.plotly_chart(_style_figure(mix, height=220), width="stretch")


def _draft_from_editor(row: pd.Series) -> TransactionDraft:
    return TransactionDraft(
        transaction_date=pd.Timestamp(row["Date"]).date(),
        description=str(row["Description"]),
        amount_cents=abs(parse_amount_cents(row["Amount"])),
        category=str(row["Category"]),
        account=str(row["Account"]),
        payment_method=str(row["Payment method"]),
        merchant=str(row["Merchant"]),
        transaction_type=str(row["Type"]),
        notes=str(row["Notes"]),
    )


@st.dialog("Delete marked transactions?")
def _confirm_delete(database: Database, transaction_ids: list[str]) -> None:
    count = len(transaction_ids)
    st.write(
        f"This will permanently delete {count} transaction"
        f"{'s' if count != 1 else ''} from the local database."
    )
    st.caption("Close this dialog to keep them.")
    if st.button("Delete permanently", type="primary"):
        deleted = database.delete_transactions(transaction_ids)
        st.toast(f"Deleted {deleted} transaction(s).")
        st.rerun()


def _render_transactions(database: Database, frame: pd.DataFrame, config: AppConfig) -> None:
    _page_heading(
        "ACTIVITY",
        "Transactions",
        "Browse comfortably or switch to the editing table when you need it.",
    )
    if frame.empty:
        st.info("No transactions match the current filters.")
        return

    view = st.segmented_control(
        "Transaction view",
        ["List", "Edit table"],
        default="List",
        label_visibility="collapsed",
    )
    if view == "List":
        _transaction_list(frame)
        return

    st.caption("Edit fields directly. Marking a row deletes it when you save.")
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
    edited = st.data_editor(
        editor_frame,
        hide_index=True,
        width="stretch",
        height=520,
        disabled=["ID"],
        column_config={
            "Delete": st.column_config.CheckboxColumn("Delete"),
            "ID": None,
            "Date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
            "Amount": st.column_config.NumberColumn(
                "Amount", min_value=0.01, step=0.01, format="$%.2f", required=True
            ),
            "Category": st.column_config.SelectboxColumn(
                "Category", options=list(config.categories), required=True
            ),
            "Type": st.column_config.SelectboxColumn(
                "Type",
                options=["expense", "refund", "income", "transfer"],
                required=True,
            ),
        },
        key="transaction_editor",
    )
    delete_ids = edited.loc[edited["Delete"], "ID"].astype(str).tolist()
    save_column, delete_column, _ = st.columns((1, 1, 4))
    if save_column.button("Save edits", type="primary"):
        try:
            for _, row in edited.iterrows():
                database.update_transaction(str(row["ID"]), _draft_from_editor(row))
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.toast("Changes saved.")
            st.rerun()
    if delete_column.button(
        f"Delete marked ({len(delete_ids)})",
        disabled=not delete_ids,
    ):
        _confirm_delete(database, delete_ids)


def _render_add(database: Database, config: AppConfig) -> None:
    _page_heading(
        "QUICK ENTRY",
        "Add a transaction",
        "A simple record, saved directly to your local database.",
    )
    with st.form("add_transaction", clear_on_submit=True):
        left, right = st.columns(2)
        transaction_date = left.date_input("Date", value=date.today())
        transaction_type = right.selectbox("Type", ["expense", "refund", "income", "transfer"])
        description = st.text_input("Description", placeholder="What was this for?")
        merchant = st.text_input("Merchant", placeholder="Optional, improves recurring analysis")
        left, right = st.columns(2)
        amount = left.number_input("Amount", min_value=0.01, step=0.01, format="%.2f")
        category = right.selectbox("Category", config.categories)
        left, right = st.columns(2)
        account = left.selectbox(
            "Account",
            config.accounts,
            index=(
                config.accounts.index(config.default_account)
                if config.default_account in config.accounts
                else 0
            ),
        )
        payment_method = right.selectbox(
            "Payment method",
            config.payment_methods,
            index=(
                config.payment_methods.index(config.default_payment_method)
                if config.default_payment_method in config.payment_methods
                else 0
            ),
        )
        notes = st.text_area("Notes", height=80)
        submitted = st.form_submit_button("Save transaction", type="primary")
    if submitted:
        try:
            database.add_transaction(
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
            st.toast("Transaction saved locally.")


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
        preview = preview_csv(import_bytes, config, database.existing_fingerprints())
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
            st.success(
                f"Imported {result.imported}; skipped {result.duplicates_skipped} duplicate(s)."
            )
            st.rerun()

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


def _render_budgets(database: Database, frame: pd.DataFrame, config: AppConfig) -> None:
    _page_heading(
        "MONTHLY PLAN",
        "Budgets",
        "Set gentle boundaries and see where you still have room.",
    )
    selected_date = st.date_input("Budget month", value=date.today(), key="budget_month")
    month = selected_date.strftime("%Y-%m")
    existing = {
        str(row["category"]): int(row["amount_cents"]) / 100 for row in database.get_budgets(month)
    }
    budget_editor = pd.DataFrame(
        {
            "Category": config.personal_categories,
            "Monthly budget": [
                existing.get(category, 0.0) for category in config.personal_categories
            ],
        }
    )
    edited = st.data_editor(
        budget_editor,
        hide_index=True,
        width="stretch",
        disabled=["Category"],
        column_config={
            "Monthly budget": st.column_config.NumberColumn(
                min_value=0.0, step=10.0, format="$%.2f"
            )
        },
    )
    if st.button("Save budgets", type="primary"):
        for _, row in edited.iterrows():
            database.set_budget(
                month,
                str(row["Category"]),
                max(0, parse_amount_cents(row["Monthly budget"])),
            )
        st.toast(f"Budgets saved for {month}.")

    status = budget_status(frame, database.get_budgets(month), month)
    if not status.empty:
        _section_heading("Progress", f"How {month} is taking shape")
        progress_rows: list[str] = []
        for _, budget in status.iterrows():
            percent = float(budget["percent_used"])
            width = min(max(percent, 0), 100)
            bar_class = "over" if percent > 100 else "near" if percent > 80 else ""
            progress_rows.append(
                f"""
                <div class="budget-row roomy">
                    <div class="budget-label">
                        <strong>{html.escape(str(budget["category"]))}</strong>
                        <span>{_currency(float(budget["spent"]))} of
                        {_currency(float(budget["budget"]))} ·
                        {_currency(float(budget["remaining"]))} remaining</span>
                    </div>
                    <div class="budget-track">
                        <div class="budget-fill {bar_class}" style="width:{width:.1f}%"></div>
                    </div>
                </div>
                """
            )
        st.html(f'<div class="budget-card wide">{"".join(progress_rows)}</div>')


def _render_insights(database: Database, frame: pd.DataFrame) -> None:
    _page_heading(
        "DEEPER VIEW",
        "Advanced insights",
        "Patterns and exceptions to explore when you want more detail.",
    )
    if frame.empty:
        st.info("Add or import transactions to unlock insights.")
        return

    savings = savings_summary(frame)
    first, second, third = st.columns(3)
    with first:
        _kpi_card(
            "Recorded income",
            _currency(float(savings["income"])),
            detail="In the selected range",
        )
    with second:
        _kpi_card(
            "Net outflow",
            _currency(float(savings["net_outflow"])),
            detail="Expenses after refunds",
        )
    with third:
        _kpi_card(
            "Savings rate",
            (
                f"{float(savings['savings_rate']):.1f}%"
                if savings["savings_rate"] is not None
                else "Add income"
            ),
            detail="Based on recorded income",
        )

    _section_heading("What changed", "Category movement from the previous month")
    drivers = spending_drivers(frame)
    if drivers.empty:
        st.info("At least two months of data are needed.")
    else:
        st.dataframe(
            drivers.head(8),
            hide_index=True,
            width="stretch",
            column_config={
                "current": st.column_config.NumberColumn("Latest month", format="$%.2f"),
                "previous": st.column_config.NumberColumn("Previous month", format="$%.2f"),
                "change": st.column_config.NumberColumn("Change", format="$%.2f"),
                "percent_change": st.column_config.NumberColumn("Change %", format="%.1f%%"),
            },
        )

    left, right = st.columns(2)
    with left:
        _section_heading("Likely recurring charges", "Stable timing and amounts")
        recurring = recurring_transactions(frame)
        if recurring.empty:
            st.info("No stable recurring pattern detected yet.")
        else:
            st.dataframe(
                recurring,
                hide_index=True,
                width="stretch",
                column_config={
                    "average_amount": st.column_config.NumberColumn("Average", format="$%.2f"),
                    "median_interval_days": st.column_config.NumberColumn(
                        "Interval", format="%.0f days"
                    ),
                },
            )
    with right:
        _section_heading("Unusual purchases", "Large relative to their category")
        anomalies = spending_anomalies(frame)
        if anomalies.empty:
            st.info("No high-confidence anomalies detected.")
        else:
            st.dataframe(
                anomalies,
                hide_index=True,
                width="stretch",
                column_config={
                    "amount": st.column_config.NumberColumn(format="$%.2f"),
                    "typical_amount": st.column_config.NumberColumn("Typical", format="$%.2f"),
                    "anomaly_score": st.column_config.NumberColumn("Score", format="%.1f"),
                },
            )

    _section_heading("Cash flow", "Income, refunds, expenses, and the resulting balance")
    cash_flow = cash_flow_by_month(frame)
    if not cash_flow.empty:
        cash_flow["month_start"] = cash_flow["month"].dt.to_timestamp()
        chart = go.Figure()
        chart.add_bar(
            x=cash_flow["month_start"],
            y=cash_flow["income"] + cash_flow["refunds"],
            name="Income + refunds",
            marker_color=PRIMARY,
        )
        chart.add_bar(
            x=cash_flow["month_start"],
            y=-cash_flow["expenses"],
            name="Expenses",
            marker_color=CORAL,
        )
        chart.add_scatter(
            x=cash_flow["month_start"],
            y=cash_flow["net_cash_flow"],
            name="Net cash flow",
            mode="lines+markers",
            line={"color": PRIMARY_DARK, "width": 2.5},
        )
        chart.update_layout(barmode="relative")
        chart.update_yaxes(tickprefix="$")
        st.plotly_chart(_style_figure(chart), width="stretch")

    _section_heading("Academic-period comparison", "A dynamic view of spending across terms")
    academic = academic_period_spending(frame)
    if not academic.empty:
        academic_chart = px.bar(
            academic,
            x="academic_period",
            y="spending",
            color="academic_year",
            text_auto="$.3s",
            labels={
                "academic_period": "Academic period",
                "spending": "Personal spending",
                "academic_year": "Academic year",
            },
            color_discrete_sequence=PALETTE,
        )
        academic_chart.update_yaxes(tickprefix="$")
        st.plotly_chart(_style_figure(academic_chart), width="stretch")

    duplicate_groups = database.duplicate_groups()
    if duplicate_groups:
        st.warning(
            f"{len(duplicate_groups)} duplicate group(s) exist. "
            "Review them in Transactions before deleting anything."
        )


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


def _inject_styles() -> None:
    st.html(
        """
        <style>
        .stApp { color: #1F2A24; background: #F5F5F0; }
        [data-testid="stSidebar"] {
            background: #ECEFEA;
            border-right: 1px solid #DCE1DA;
        }
        [data-testid="stSidebar"] * { color: #38443D; }
        [data-testid="stMetric"] {
            background: #FFFFFF;
            border: 1px solid #E2E6E0;
            border-radius: 15px;
            padding: 16px 18px;
            box-shadow: none;
        }
        [data-testid="stMetricLabel"] { color: #6F7C74; }
        .empty-card {
            padding: 48px;
            border-radius: 20px;
            background: linear-gradient(135deg, #EEF3ED, #F7F3E8);
            border: 1px solid #DCE4DC;
            margin-top: 20px;
        }
        .empty-card h2 { margin: 8px 0; font-size: 2rem; }
        .empty-card p { color: #6F7C74; max-width: 620px; font-size: .96rem; }
        .eyebrow {
            color: #3D6B57;
            letter-spacing: .12em;
            font-weight: 700;
            font-size: .75rem;
        }
        h1, h2, h3 { letter-spacing: -0.02em; }
        div[data-testid="stDataFrame"] {
            border: 1px solid #E2E6E0;
            border-radius: 13px;
            overflow: hidden;
        }
        .block-container {
            max-width: 1220px;
            padding-top: 2.8rem;
            padding-bottom: 4rem;
        }
        [data-testid="stHeader"] { background: rgba(245,245,240,.88); }
        [data-testid="stSidebar"] div[role="radiogroup"] label {
            border-radius: 10px;
            padding: .42rem .6rem;
            margin: .08rem 0;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] label:hover {
            background: rgba(61,107,87,.07);
        }
        .wordmark {
            display: flex;
            align-items: center;
            gap: 10px;
            color: #254C3D;
            font-size: 1.08rem;
            font-weight: 720;
            letter-spacing: -.02em;
            margin: .4rem 0 .2rem;
        }
        .wordmark-mark {
            display: grid;
            place-items: center;
            width: 28px;
            height: 28px;
            border-radius: 9px;
            background: #3D6B57;
            color: white !important;
            font-size: .85rem;
        }
        .sidebar-subtitle {
            color: #7B867F;
            font-size: .78rem;
            margin-bottom: 1.4rem;
        }
        .local-pill {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            padding: 7px 10px;
            border: 1px solid #D6DDD6;
            background: rgba(255,255,255,.6);
            border-radius: 999px;
            color: #526158;
            font-size: .74rem;
        }
        .local-pill::before,
        .privacy-dot {
            content: "";
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #4F8069;
            box-shadow: 0 0 0 3px rgba(79,128,105,.12);
            flex: none;
        }
        .page-heading { margin-bottom: 1.7rem; }
        .page-heading h1 {
            color: #1F2A24;
            font-size: clamp(2rem,3vw,2.75rem);
            line-height: 1.05;
            font-weight: 660;
            letter-spacing: -.045em;
            margin: .35rem 0 .55rem;
        }
        .page-kicker {
            color: #3D6B57;
            letter-spacing: .13em;
            font-weight: 720;
            font-size: .68rem;
        }
        .page-description {
            color: #6F7C74;
            max-width: 680px;
            font-size: .98rem;
            margin: 0;
        }
        .section-heading {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 18px;
            margin: 2.1rem 0 .8rem;
        }
        .section-heading h2 {
            color: #1F2A24;
            font-size: 1.18rem;
            font-weight: 650;
            letter-spacing: -.025em;
            margin: 0;
        }
        .section-heading span {
            color: #6F7C74;
            font-size: .78rem;
            text-align: right;
        }
        .kpi-card {
            min-height: 150px;
            background: #FFFFFF;
            border: 1px solid #E2E6E0;
            border-radius: 17px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: 0 3px 14px rgba(37,52,43,.035);
        }
        .kpi-card.featured {
            background: #254C3D;
            border-color: #254C3D;
        }
        .kpi-label {
            color: #6F7C74;
            font-size: .76rem;
            font-weight: 590;
        }
        .kpi-value {
            color: #1F2A24;
            font-size: clamp(1.55rem,2.1vw,2.15rem);
            font-weight: 650;
            letter-spacing: -.045em;
            white-space: nowrap;
        }
        .kpi-foot {
            display: flex;
            align-items: center;
            gap: 8px;
            color: #89928D;
            font-size: .69rem;
            min-height: 22px;
        }
        .kpi-card.featured .kpi-label,
        .kpi-card.featured .kpi-foot { color: #C8D6CE; }
        .kpi-card.featured .kpi-value { color: #FFFFFF; }
        .kpi-change {
            border-radius: 999px;
            padding: 3px 7px;
            font-size: .66rem;
            font-weight: 700;
        }
        .kpi-change.calm { background: #E5F2E9; color: #35674F; }
        .kpi-change.attention { background: #F5E4E0; color: #9C4F47; }
        .insight-card,
        .budget-card,
        .soft-empty {
            background: rgba(255,255,255,.72);
            border: 1px solid #E2E6E0;
            border-radius: 16px;
            padding: 8px 18px;
        }
        .insight-row {
            display: flex;
            align-items: flex-start;
            gap: 12px;
            color: #59645E;
            font-size: .84rem;
            line-height: 1.42;
            padding: 14px 2px;
            border-bottom: 1px solid #E9ECE8;
        }
        .insight-row:last-child,
        .budget-row:last-child,
        .transaction-row:last-child { border-bottom: none; }
        .insight-row strong {
            color: #1F2A24;
            display: block;
            font-weight: 630;
        }
        .insight-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-top: 5px;
            background: #A4AAA6;
            flex: none;
        }
        .insight-dot.calm { background: #3D6B57; }
        .insight-dot.attention { background: #C9685D; }
        .insight-dot.neutral { background: #C59A4A; }
        .budget-card { padding: 8px 18px 12px; }
        .budget-card.wide { padding: 12px 22px 16px; }
        .budget-row {
            padding: 12px 0;
            border-bottom: 1px solid #E9ECE8;
        }
        .budget-row.roomy { padding: 17px 0; }
        .budget-label {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 12px;
            margin-bottom: 8px;
        }
        .budget-label strong {
            color: #1F2A24;
            font-size: .8rem;
            font-weight: 620;
        }
        .budget-label span {
            color: #6F7C74;
            font-size: .7rem;
            text-align: right;
        }
        .budget-track {
            height: 6px;
            border-radius: 99px;
            overflow: hidden;
            background: #E8ECE7;
        }
        .budget-fill {
            height: 100%;
            border-radius: inherit;
            background: #3D6B57;
        }
        .budget-fill.near { background: #C59A4A; }
        .budget-fill.over { background: #C9685D; }
        .soft-empty {
            min-height: 180px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            color: #6F7C74;
        }
        .soft-empty strong { color: #1F2A24; margin-bottom: 5px; }
        .transaction-list {
            background: rgba(255,255,255,.7);
            border: 1px solid #E2E6E0;
            border-radius: 16px;
            padding: 0 18px;
        }
        .transaction-row {
            display: flex;
            justify-content: space-between;
            gap: 18px;
            padding: 15px 2px;
            border-bottom: 1px solid #E8EBE7;
        }
        .transaction-title {
            color: #1F2A24;
            font-weight: 620;
            font-size: .88rem;
        }
        .transaction-note {
            color: #66736B;
            font-size: .76rem;
            margin-top: 2px;
        }
        .transaction-meta {
            color: #8A938D;
            font-size: .69rem;
            margin-top: 4px;
        }
        .transaction-amount {
            font-variant-numeric: tabular-nums;
            font-weight: 640;
            font-size: .85rem;
            white-space: nowrap;
        }
        .transaction-amount.expense { color: #39443E; }
        .transaction-amount.income { color: #3D6B57; }
        .transaction-amount.transfer { color: #6F7C74; }
        .privacy-strip,
        .privacy-hero {
            display: flex;
            align-items: center;
            gap: 12px;
            color: #526159;
            background: rgba(221,235,227,.7);
            border: 1px solid #CEDFD4;
            border-radius: 13px;
            padding: 13px 16px;
            font-size: .8rem;
            margin-bottom: 1.5rem;
        }
        .privacy-hero { padding: 18px; }
        .privacy-hero strong { display: block; color: #254C3D; }
        .privacy-hero span { color: #66746C; font-size: .75rem; }
        div[data-testid="stDataEditor"] {
            border: 1px solid #E2E6E0;
            border-radius: 13px;
            overflow: hidden;
        }
        [data-testid="stForm"] {
            background: rgba(255,255,255,.72);
            border: 1px solid #E2E6E0;
            border-radius: 17px;
            padding: 22px;
        }
        [data-testid="stExpander"] {
            background: rgba(255,255,255,.48);
            border-color: #E2E6E0;
            border-radius: 13px;
        }
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            background: #254C3D;
            border-color: #254C3D;
            border-radius: 10px;
        }
        .stButton > button:not([kind="primary"]),
        .stDownloadButton > button {
            border-color: #CFD6CF;
            border-radius: 10px;
        }
        h1, h2, h3 { color: #1F2A24; }
        hr { border-color: #E2E6E0 !important; }
        @media (max-width: 800px) {
            .block-container { padding-top: 1.7rem; }
            .kpi-card { min-height: 128px; }
            .section-heading {
                align-items: flex-start;
                flex-direction: column;
                gap: 3px;
            }
            .section-heading span { text-align: left; }
            .budget-label {
                align-items: flex-start;
                flex-direction: column;
            }
        }
        </style>
        """
    )


def render_app() -> None:
    st.set_page_config(
        page_title="Local Spending",
        page_icon="◒",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles()
    database = _database()
    config = load_config()

    with st.sidebar:
        st.html(
            """
            <div class="wordmark">
                <span class="wordmark-mark">$</span>
                <span>Local Spending</span>
            </div>
            <div class="sidebar-subtitle">A private view of your money</div>
            """
        )
    page = st.sidebar.radio(
        "Navigate",
        [
            "Overview",
            "Transactions",
            "Add transaction",
            "Import / Export",
            "Budgets",
            "Advanced insights",
            "Settings",
        ],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    with st.sidebar:
        st.html('<span class="local-pill">Local database</span>')

    rows, frame = _filtered_data(database, config)
    if page == "Overview":
        _render_dashboard(database, frame)
    elif page == "Transactions":
        _render_transactions(database, frame, config)
    elif page == "Add transaction":
        _render_add(database, config)
    elif page == "Import / Export":
        _render_import_export(database, rows, config)
    elif page == "Budgets":
        _render_budgets(database, frame, config)
    elif page == "Advanced insights":
        _render_insights(database, frame)
    else:
        _render_settings(database, config)
