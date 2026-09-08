"""Student spending-plan setup and monthly/quarterly dashboard."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from .config import AppConfig
from .database import Database
from .presentation import budget_hero_markup, usage_markup
from .spending_plan import Commitment, SpendingPlan, calculate_plan, month_after
from .university_presets import UCLA_2026, ucla_benchmark


def money(cents: int) -> str:
    return f"{'−' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


def cents(value: object) -> int:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Enter a nonnegative dollar amount for every bill.")
        return int((amount * 100).quantize(Decimal("1")))
    except (InvalidOperation, TypeError) as error:
        raise ValueError("Enter a valid dollar amount for every bill.") from error


def _default_costs(benchmark: dict) -> list[dict]:
    return [
        {
            "Bill": "Tuition + nonresident tuition",
            "Amount ($)": (
                benchmark["Tuition + student services"] + benchmark["Nonresident tuition"]
            )
            / 100,
            "Cycle": "Coverage total",
            "First month": 1,
            "Months": 9,
            "Categories": "Tuition",
        },
        {
            "Bill": "Campus fees",
            "Amount ($)": benchmark["Campus fees"] / 100,
            "Cycle": "Coverage total",
            "First month": 1,
            "Months": 9,
            "Categories": "School Fees",
        },
        {
            "Bill": "Rent / housing + meal plan",
            "Amount ($)": 0.0,
            "Cycle": "Monthly",
            "First month": 1,
            "Months": 9,
            "Categories": "Rent, Housing and Meal Plan",
        },
        {
            "Bill": "Utilities",
            "Amount ($)": 0.0,
            "Cycle": "Monthly",
            "First month": 1,
            "Months": 9,
            "Categories": "Utilities",
        },
        {
            "Bill": "Internet",
            "Amount ($)": 0.0,
            "Cycle": "Monthly",
            "First month": 1,
            "Months": 9,
            "Categories": "Internet",
        },
        {
            "Bill": "Health insurance",
            "Amount ($)": benchmark["Insurance"] / 100,
            "Cycle": "Coverage total",
            "First month": 1,
            "Months": 9,
            "Categories": "Insurance",
        },
    ]


def _setup(database: Database, plan: SpendingPlan | None) -> None:
    st.subheader("Make the plan yours")
    st.caption(
        "UCLA undergraduate estimates are a starting point, not a bill or available cash. "
        "Nothing is saved until you confirm your costs."
    )
    if plan is None:
        first, second, third = st.columns(3)
        cohort = first.selectbox("UC entry cohort", list(UCLA_2026["cohorts"]))
        housing = second.selectbox("Housing benchmark", list(UCLA_2026["housing"]))
        residency = third.selectbox("Tuition residency", ["Choose…", "CA resident", "Nonresident"])
        components = ucla_benchmark(cohort, housing, residency == "Nonresident")
        reference = {
            "preset_id": UCLA_2026["id"],
            "school": "UCLA",
            "year": UCLA_2026["academic_year"],
            "cohort": cohort,
            "housing": housing,
            "residency": residency,
            "source": UCLA_2026["source"],
            "verified_on": UCLA_2026["verified_on"],
            "components": components,
        }
        editor_rows = _default_costs(components)
        editor_key = f"plan_costs_{cohort}_{housing}_{residency}"
    else:
        reference = plan.reference
        residency = reference["residency"]
        editor_rows = [
            {
                "Bill": cost.name,
                "Amount ($)": cost.amount_cents / 100,
                "Cycle": cost.cadence,
                "First month": cost.first_month + 1,
                "Months": cost.months,
                "Categories": ", ".join(cost.categories),
            }
            for cost in plan.commitments
        ]
        editor_key = f"plan_costs_saved_{hash(str(plan.to_dict()))}"
        st.caption(
            f"Saved reference: {reference['school']} {reference['year']} · "
            f"{reference['cohort']} cohort · {reference['housing']} · {residency}. "
            "The reference stays frozen; your targets and actual bills remain editable."
        )
    st.markdown(
        f"[UCLA reference estimates]({reference['source']}) · "
        f"verified {reference['verified_on']}. Tuition includes the student services fee; "
        "campus fees and insurance are separate."
    )
    with st.form("student_plan_setup"):
        name = st.text_input("Plan name", value=plan.name if plan else "My UCLA spending plan")
        first, second = st.columns(2)
        start = first.date_input(
            "First budget month", value=plan.start if plan else date(2026, 10, 1)
        )
        duration = second.selectbox(
            "Coverage (months)", [9, 12], index=plan.months // 3 - 3 if plan else 0
        )
        st.caption(
            "Dates use full months. Quarters are three-month budget blocks from your start month, "
            "not UCLA instruction dates. A 12-month lease needs 12 months of costs "
            "and a summer target."
        )
        a, b, c = st.columns(3)
        academic = a.number_input(
            "9-month target ($)",
            min_value=0.0,
            step=100.0,
            value=(plan.academic_target_cents if plan else sum(reference["components"].values()))
            / 100,
        )
        summer = b.number_input(
            "Extra summer target ($)",
            min_value=0.0,
            step=100.0,
            value=plan.summer_target_cents / 100 if plan else 0.0,
        )
        buffer = c.number_input(
            "Protected buffer — whole plan ($)",
            min_value=0.0,
            step=50.0,
            value=plan.buffer_cents / 100 if plan else 0.0,
        )
        st.markdown("**Committed costs**")
        st.caption(
            "Enter your real rent and utilities, including summer if needed. Amount is per month, "
            "per three-month cycle, or the total for the coverage. Month 1 is the start above. "
            "For prepaid insurance or annual tuition, use Coverage total. Add books, flights, "
            "phone, or other reserves as extra rows. Zero means no planned reserve."
        )
        edited = st.data_editor(
            pd.DataFrame(editor_rows),
            key=editor_key,
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "Amount ($)": st.column_config.NumberColumn(
                    min_value=0.0, format="$%.2f", required=True
                ),
                "Cycle": st.column_config.SelectboxColumn(
                    options=["Monthly", "Quarterly", "Coverage total"], required=True
                ),
                "First month": st.column_config.NumberColumn(
                    min_value=1, max_value=12, step=1, required=True
                ),
                "Months": st.column_config.NumberColumn(
                    min_value=1, max_value=12, step=1, required=True
                ),
                "Bill": st.column_config.TextColumn(required=True),
                "Categories": st.column_config.TextColumn(
                    help="Exact, comma-separated transaction categories"
                ),
            },
        )
        st.caption(
            "Each category can match only one bill in a given month. A combined housing/meal-plan "
            "charge should be reserved once. Unmatched expenses—including uncategorized ones—"
            "always count as everyday spending. Create additional categories in config.toml."
        )
        confirmed = st.checkbox(
            "I checked my residency, tuition, rent, utilities, insurance and summer coverage. "
            "Zero amounts and any unmatched bills are intentional."
        )
        submitted = st.form_submit_button("Save spending plan", type="primary")
    if submitted:
        if not confirmed or residency == "Choose…":
            st.error("Choose your residency and confirm your costs before saving.")
            return
        try:
            costs = tuple(
                Commitment(
                    name=str(row["Bill"] or "").strip(),
                    amount_cents=cents(row["Amount ($)"]),
                    cadence=str(row["Cycle"]),
                    first_month=int(row["First month"]) - 1,
                    months=int(row["Months"]),
                    categories=tuple(
                        item.strip()
                        for item in str(row["Categories"] or "").split(",")
                        if item.strip()
                    ),
                )
                for row in edited.to_dict("records")
            )
            updated = SpendingPlan(
                name=name,
                start=start.replace(day=1),
                months=duration,
                academic_target_cents=cents(academic),
                summer_target_cents=cents(summer),
                buffer_cents=cents(buffer),
                commitments=costs,
                reference=reference,
                allocations=plan.allocations if plan else {},
            ).validate()
            database.save_spending_plan(updated)
        except (ValueError, TypeError, OverflowError) as error:
            st.error(f"Could not save: {error}")
            return
        st.session_state["plan_saved"] = True
        st.rerun()


def _payment_allocations(database: Database, plan: SpendingPlan, rows: list[dict]) -> None:
    with st.expander("Payment timing & transaction review"):
        st.caption(
            "Tuition paid before the term, or a refund for an earlier bill? Assign its budget "
            "month here. This changes only this plan, never the original transaction or cash flow. "
            "Refunds should use the same bill coverage as the original expense."
        )
        candidates = [row for row in rows if row["transaction_type"] in ("expense", "refund")]
        if not candidates:
            st.info("No expense or refund transactions recorded yet.")
            return
        lookup = {row["id"]: row for row in candidates}
        selected = st.selectbox(
            "Payment",
            list(lookup),
            format_func=lambda key: (
                f"{lookup[key]['transaction_date']} · {lookup[key]['description']} · "
                f"{money(lookup[key]['amount_cents'])} · {lookup[key]['transaction_type']}"
            ),
        )
        options = ["Use transaction date", *plan.month_keys]
        budget_month = st.selectbox(
            "Assign to",
            options,
            index=options.index(plan.allocations.get(selected, options[0])),
            key=f"payment_month_{selected}_{plan.allocations.get(selected, '')}",
        )
        if st.button("Save payment timing"):
            allocations = dict(plan.allocations)
            if budget_month == options[0]:
                allocations.pop(selected, None)
            else:
                allocations[selected] = budget_month
            database.save_spending_plan(replace(plan, allocations=allocations))
            st.rerun()
        if plan.allocations:
            st.caption(f"{len(plan.allocations)} explicit payment allocation(s) saved locally.")


def render_budget_page(database: Database, config: AppConfig) -> None:
    plan = database.get_spending_plan()
    if st.session_state.pop("plan_saved", False):
        st.success("Spending plan saved locally.")
    if plan is None:
        _setup(database, None)
        return
    rows = database.list_transactions()  # Deliberately independent of sidebar filters.
    result = calculate_plan(plan, rows)
    st.caption(
        f"{plan.name} · {plan.start:%b %Y}–{month_after(plan.start, plan.months - 1):%b %Y} · "
        "All recorded expenses included; activity filters do not apply."
    )
    first, second = st.columns([1, 2])
    view = first.radio("View", ["Monthly", "Quarterly"], horizontal=True)
    today = date.today()
    current = min(
        max((today.year - plan.start.year) * 12 + today.month - plan.start.month, 0),
        plan.months - 1,
    )
    if view == "Monthly":
        index = second.selectbox(
            "Budget month",
            range(plan.months),
            index=current,
            format_func=lambda i: month_after(plan.start, i).strftime("%B %Y"),
        )
        period = result["months"][index]
        start, end = month_after(plan.start, index), month_after(plan.start, index + 1)
        period_keys = [period["month"]]
    else:
        index = second.selectbox(
            "Budget quarter",
            range(plan.months // 3),
            index=current // 3,
            format_func=lambda i: (
                f"Q{i + 1} · {month_after(plan.start, i * 3):%b %Y}–"
                f"{month_after(plan.start, i * 3 + 2):%b %Y}"
            ),
        )
        period = result["quarters"][index]
        start, end = month_after(plan.start, index * 3), month_after(plan.start, index * 3 + 3)
        period_keys = period["months"]
    remaining = period["remaining"]
    st.html(budget_hero_markup(period))
    capacity = period["allowance"] + period.get("rollover", 0)
    meter, c = st.columns([3, 1])
    with meter:
        st.html(usage_markup(period["flexible_spent"], capacity))
    if today >= end:
        c.metric("Weekly guide", "Period ended")
    else:
        days = (end - max(today, start)).days
        c.metric("Weekly guide", money(round(max(remaining, 0) * min(days, 7) / days)))
    if view == "Monthly":
        st.caption(
            f"Carry from earlier months in this quarter: {money(period['rollover'])}. "
            "Both unused allowance and overspending carry forward; quarters reset."
        )
    if period["allowance"] < 0:
        st.warning(
            "Committed costs and buffer exceed this quarter’s target. "
            "There is no positive everyday allowance."
        )
    elif remaining < 0:
        st.warning(
            "Everyday spending exceeds the available allowance. "
            "The shortfall is kept in the calculation."
        )
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Where the target goes")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Allocation": "Spending target", "Amount": money(period["target"])},
                    {
                        "Allocation": "Committed costs · reserved or paid",
                        "Amount": money(period["reserved"]),
                    },
                    {"Allocation": "Protected buffer", "Amount": money(period["buffer"])},
                    {
                        "Allocation": "Quarter smoothing adjustment",
                        "Amount": money(
                            period["allowance"]
                            - period["target"]
                            + period["reserved"]
                            + period["buffer"]
                        ),
                    },
                    {
                        "Allocation": "Everyday allowance · smoothed within quarter",
                        "Amount": money(period["allowance"]),
                    },
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    with right:
        st.subheader("Everyday spending")
        categories: dict[str, int] = {}
        for month in result["months"]:
            if month["month"] in period_keys:
                for category, amount in month["categories"].items():
                    categories[category] = categories.get(category, 0) + amount
        if categories:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Category": key, "Net spent": money(value)}
                        for key, value in sorted(categories.items(), key=lambda item: -item[1])
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No everyday expenses recorded for this period.")
        if "Uncategorized" in categories:
            st.warning("Uncategorized expenses are included. Review them for any bill payments.")
    with st.expander("Bills & reserves", expanded=False):
        st.caption(
            "Whole bill cycles overlapping this view, not cash due this month. Paying a bill "
            "replaces its reserve; spending above the reserve reduces your allowance. "
            "If a finalized bill costs less, lower its planned amount to release the difference."
        )
        bill_rows = []
        for bill in result["obligations"]:
            coverage = [plan.month_keys[i] for i in bill["coverage"]]
            if not set(coverage).intersection(period_keys):
                continue
            bill_rows.append(
                {
                    "Bill": bill["name"],
                    "Coverage": f"{coverage[0]} → {coverage[-1]}",
                    "Planned": money(bill["planned"]),
                    "Net paid": money(bill["paid"]),
                    "Still reserved": money(bill["unpaid"]),
                    "Over plan": money(max(0, bill["paid"] - bill["planned"])),
                }
            )
        st.dataframe(pd.DataFrame(bill_rows), hide_index=True, width="stretch")
    with st.expander("Whole-plan outlook & benchmark"):
        st.caption(
            f"Reference: {plan.reference['school']} {plan.reference['year']}, "
            f"{plan.reference['cohort']} cohort · "
            f"snapshot verified {plan.reference['verified_on']}. "
            "Future months assume no additional everyday spending. "
            "This is not a cash-flow forecast."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Quarter": f"Q{i + 1} · {q['months'][0]}–{q['months'][-1]}",
                        "Target": money(q["target"]),
                        "Committed": money(q["reserved"]),
                        "Everyday allowance": money(q["allowance"]),
                        "Net spent": money(q["flexible_spent"]),
                        "Remaining": money(q["remaining"]),
                    }
                    for i, q in enumerate(result["quarters"])
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        benchmark = sum(plan.reference["components"].values())
        st.caption(
            f"Nine-month UCLA reference: {money(benchmark)} · Your nine-month target: "
            f"{money(plan.academic_target_cents)} · "
            f"Extra summer: {money(plan.summer_target_cents)}. "
            "The benchmark already includes housing and food; your actual costs replace, "
            "not add to, those allowances. "
            "Insurance savings do not automatically lower your target."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Reference component": key, "9-month amount": money(value)}
                    for key, value in plan.reference["components"].items()
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    _payment_allocations(database, plan, rows)
    with st.expander("Expenses included in this period"):
        included = [row for row in result["transactions"] if row["budget_month"] in period_keys]
        if included:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Date": row["transaction_date"],
                            "Budget month": row["budget_month"],
                            "Description": row["description"],
                            "Category": row["category"],
                            "Counted as": row["budget_bucket"],
                            "Net amount": money(row["net_cents"]),
                        }
                        for row in included
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No recorded expenses or refunds allocated to this period.")
    with st.expander("Edit plan & committed costs"):
        _setup(database, plan)
    with st.expander("How this is calculated"):
        st.write(
            "Target − committed costs − buffer = everyday allowance. Bill cycles are spread over "
            "their coverage months, then everyday allowance is smoothed within each quarter. "
            "Monthly remaining includes prior months in the same quarter; quarterly remaining "
            "uses that quarter’s total spending. Income and transfers do not change the target. "
            "All matching uses exact categories, not the older Fixed/Personal grouping. "
            "Payment dates remain unchanged in other pages."
        )
        st.caption("Available transaction categories: " + ", ".join(config.categories))
