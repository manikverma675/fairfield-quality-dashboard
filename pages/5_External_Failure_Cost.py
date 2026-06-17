import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    claims_by_item,
    claims_by_reason,
    external_failure_summary,
)
from quality_dashboard.config import EXTERNAL_FAILURE_FILE
from quality_dashboard.data_loaders import load_external_failure_data
from quality_dashboard.metrics import format_currency_short
from quality_dashboard.ui import (
    CHART_BLUE,
    CHART_ORANGE,
    bar_chart,
    empty_state,
    file_missing,
    render_header,
    selected_value,
)




@st.cache_data(show_spinner=False)
def cached_external_failure():
    return load_external_failure_data(EXTERNAL_FAILURE_FILE)


if not EXTERNAL_FAILURE_FILE.exists():
    file_missing(EXTERNAL_FAILURE_FILE)

external_failure = cached_external_failure()
top_claims = external_failure.top_claims
department_summary = external_failure.department_summary

if top_claims.empty:
    empty_state("No external failure claim rows were found in the source file.")

render_header(
    "External Failure Cost",
    "Walmart claim cost by reason, department, item, and defect/damage category.",
    EXTERNAL_FAILURE_FILE.name,
)

reasons = sorted(top_claims["Claim Reason"].dropna().unique())
with st.sidebar:
    st.header("Filters")
    selected_reasons = st.multiselect("Claim reason", reasons, default=[])
    _top_n_label = st.selectbox("Top items shown", [10, 15, 20, 25, 30, 50, 75, 100, "All"], index=1)
    top_n = None if _top_n_label == "All" else _top_n_label

filtered_claims = top_claims.copy()
if selected_reasons:
    filtered_claims = filtered_claims[filtered_claims["Claim Reason"].isin(selected_reasons)]
if filtered_claims.empty:
    empty_state("No claim rows match the selected filters.")

summary = external_failure_summary(filtered_claims)
dept_total = department_summary["Claim Amount"].sum() if not department_summary.empty else float("nan")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Dept Summary Total", format_currency_short(dept_total))
col2.metric("Top Items Cost", format_currency_short(summary["total_claims"]))
col3.metric("Claim Lines", f"{summary['claim_rows']:,}")
col4.metric("Defect/Damage Cost", format_currency_short(summary["defect_damage_cost"]))
col5.metric("Defect/Damage Units", f"{summary['defect_damage_units']:,}")
st.caption(
    "Dept Summary Total is the full retailer-reported total and does not change with filters. "
    "Top Items Cost is filtered by reason and covers only the line-item detail sheet — "
    f"the {format_currency_short(dept_total - summary['total_claims'])} gap is claims not in that sheet. "
    "Defect/Damage Cost and Units count only *Defective Merchandise* and *Damaged MD to 0* claim lines."
)

with st.expander("Formulas & Methodology"):
    st.markdown("""
**Where the numbers come from**

This page pulls from two separate tabs inside the source Excel file. They are independent Walmart reports and their totals will not exactly match each other — this is expected.

| Tab | What it contains | Affected by claim reason filter? |
|---|---|---|
| Department Summary | Walmart's rolled-up claim totals by department. One row per department. | No — always shows the full period total. |
| Line-Item Detail (Top Claimed Items) | Individual claim lines with one row per item per claim reason. This is the detail behind the department totals. | Yes — filtering by reason removes rows from this sheet only. |

---

**Metric Cards**

| Metric | How it is calculated |
|---|---|
| Dept Summary Total | Sum of the *Claim Amount* column across every row in the Department Summary tab. This is the retailer's stated grand total for the period and **does not change** when you filter by claim reason. |
| Top Items Cost | Sum of *Claim Amount* from the Line-Item Detail tab, after applying the selected claim reason filter. This will always be less than or equal to the Dept Summary Total because not every claim type has individual item lines in the detail sheet. |
| Claim Lines | Count of rows in the Line-Item Detail tab after filtering. One row = one item charged under one claim reason. |
| Defect/Damage Cost | Sum of *Claim Amount* for rows where Claim Reason is **Defective Merchandise** or **Damaged MD to 0**, after filtering. Shows how much of the total cost is driven by product quality and damage issues specifically. |
| Defect/Damage Units | Count of claim lines where Claim Reason is **Defective Merchandise** or **Damaged MD to 0**, after filtering. |

The dollar gap between *Dept Summary Total* and *Top Items Cost* is money that Walmart charged at the department level but did not break down to individual items in the detail sheet — for example, freight allowances or category-level deductions.

---

**Charts**

| Chart | How it is calculated |
|---|---|
| Claim Cost by Reason | Groups every row in the Line-Item Detail tab by *Claim Reason* and sums their *Claim Amount*. Shows which type of claim (e.g. damaged, defective, shortage) is costing the most money. Click a bar to list that reason's individual claim lines below. |
| Claim Cost by Department | Groups the Department Summary tab by *Department Description* and sums *Claim Amount* per department. Shows which product departments are generating the most claim dollars according to Walmart's own rolled-up report. *(Not clickable — the detail sheet has no department column to drill into.)* |
| Top Items by Claim Cost | Groups the Line-Item Detail tab by *Item Description*, sums *Claim Amount* per item, and ranks from highest to lowest. Shows which specific products are responsible for the most claim dollars in the detail sheet. The dropdown controls how many items appear — select **All** to show every item. Click a bar to list that item's individual claim lines below. |
""")

tab_cost, tab_items, tab_records = st.tabs(["Cost", "Items", "Records"])

with tab_cost:
    reason_summary = claims_by_reason(filtered_claims)
    left, right = st.columns(2)
    with left:
        reason_event = st.altair_chart(
            bar_chart(
                reason_summary,
                "Claim Amount",
                "Claim Reason",
                "Claim Cost by Reason — click a bar to filter",
                color=CHART_BLUE,
                x_format="$,.0f",
                selectable=True,
            ),
            width="stretch",
            on_select="rerun",
            key="ef_reason_chart",
        )
    with right:
        dept_chart_data = department_summary.sort_values("Claim Amount", ascending=False)
        st.altair_chart(
            bar_chart(
                dept_chart_data,
                "Claim Amount",
                "Department Description",
                "Claim Cost by Department",
                color=CHART_ORANGE,
                x_format="$,.0f",
            ),
            width="stretch",
        )

    st.subheader("Reason Summary")
    st.dataframe(reason_summary, width="stretch", hide_index=True)

    selected_reason = selected_value(reason_event, "Claim Reason")
    if selected_reason:
        reason_rows = filtered_claims[filtered_claims["Claim Reason"] == selected_reason]
        st.subheader(f"Claim lines — {selected_reason} ({len(reason_rows)} rows)")
        st.caption("Click the same bar again to clear.")
        st.dataframe(
            reason_rows.sort_values("Claim Amount", ascending=False)[
                [c for c in ["UPC", "Item Description", "Item Number", "Claim Amount", "Claim Reason"] if c in reason_rows.columns]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Click a bar in *Claim Cost by Reason* to list its individual claim lines here. (The Department chart isn't clickable — the source detail sheet has no department column to drill into.)")

with tab_items:
    item_summary = claims_by_item(filtered_claims, limit=top_n)

    item_event = st.altair_chart(
        bar_chart(
            item_summary,
            "Claim Amount",
            "Item Description",
            f"Top {len(item_summary)} Items by Claim Cost — click a bar to filter",
            x_format="$,.0f",
            selectable=True,
        ),
        width="stretch",
        on_select="rerun",
        key="ef_item_chart",
    )

    st.subheader("Top Claimed Items")
    st.dataframe(item_summary, width="stretch", hide_index=True)

    selected_item = selected_value(item_event, "Item Description")
    if selected_item:
        item_rows = filtered_claims[filtered_claims["Item Description"] == selected_item]
        st.subheader(f"Claim lines — {selected_item} ({len(item_rows)} rows)")
        st.caption("Click the same bar again to clear.")
        st.dataframe(
            item_rows.sort_values("Claim Amount", ascending=False)[
                [c for c in ["UPC", "Item Description", "Item Number", "Claim Amount", "Claim Reason"] if c in item_rows.columns]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Click a bar above to list that item's individual claim lines here.")

with tab_records:
    visible_claims = [
        "UPC",
        "Item Description",
        "Item Number",
        "Claim Amount",
        "Claim Reason",
    ]
    visible_claims = [column for column in visible_claims if column in filtered_claims.columns]
    st.subheader("Claim Rows")
    st.dataframe(
        filtered_claims.sort_values("Claim Amount", ascending=False)[visible_claims],
        width="stretch",
        hide_index=True,
    )

    st.subheader("Department Summary")
    st.dataframe(department_summary, width="stretch", hide_index=True)
