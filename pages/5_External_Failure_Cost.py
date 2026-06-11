import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    claims_by_item,
    claims_by_reason,
    defective_damage_summary,
    external_failure_summary,
)
from quality_dashboard.config import EXTERNAL_FAILURE_FILE
from quality_dashboard.data_loaders import load_external_failure_data
from quality_dashboard.metrics import format_currency_short, format_number
from quality_dashboard.ui import (
    CHART_BLUE,
    CHART_ORANGE,
    bar_chart,
    empty_state,
    file_missing,
    render_header,
)




@st.cache_data(show_spinner=False)
def cached_external_failure():
    return load_external_failure_data(EXTERNAL_FAILURE_FILE)


if not EXTERNAL_FAILURE_FILE.exists():
    file_missing(EXTERNAL_FAILURE_FILE)

external_failure = cached_external_failure()
top_claims = external_failure.top_claims
department_summary = external_failure.department_summary
defective_damaged = external_failure.defective_damaged

if top_claims.empty:
    empty_state("No external failure claim rows were found in the source file.")

render_header(
    "External Failure Cost",
    "Amazon claim cost by reason, department, item, and defect/damage category.",
    EXTERNAL_FAILURE_FILE.name,
)

reasons = sorted(top_claims["Claim Reason"].dropna().unique())
with st.sidebar:
    st.header("Filters")
    selected_reasons = st.multiselect("Claim reason", reasons, default=[])
    top_n = st.slider("Top items shown", 5, 30, 15)

filtered_claims = top_claims.copy()
if selected_reasons:
    filtered_claims = filtered_claims[filtered_claims["Claim Reason"].isin(selected_reasons)]
if filtered_claims.empty:
    empty_state("No claim rows match the selected filters.")

summary = external_failure_summary(filtered_claims, defective_damaged)
dept_total = department_summary["Claim Amount"].sum() if not department_summary.empty else float("nan")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Dept Summary Total", format_currency_short(dept_total))
col2.metric("Top Items Cost", format_currency_short(summary["total_claims"]))
col3.metric("Claim Lines", f"{summary['claim_rows']:,}")
col4.metric("Defect/Damage Cost †", format_currency_short(summary["defect_damage_cost"]))
col5.metric("Defect/Damage Units †", format_number(summary["defect_damage_units"]))
st.caption(
    "Dept Summary Total is the full Amazon-reported total and does not change with filters. "
    "Top Items Cost is filtered by reason and covers only the line-item detail sheet — "
    f"the {format_currency_short(dept_total - summary['total_claims'])} gap is claims not in that sheet. "
    "† Defect/Damage figures are not filterable by claim reason."
)

tab_cost, tab_items, tab_records = st.tabs(["Cost", "Items", "Records"])

with tab_cost:
    reason_summary = claims_by_reason(filtered_claims)
    left, right = st.columns(2)
    with left:
        st.altair_chart(
            bar_chart(
                reason_summary,
                "Claim Amount",
                "Claim Reason",
                "Claim Cost by Reason",
                color=CHART_BLUE,
                x_format="$,.0f",
            ),
            width="stretch",
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

with tab_items:
    item_summary = claims_by_item(filtered_claims, limit=top_n)
    damage_summary = defective_damage_summary(defective_damaged, limit=top_n)

    st.altair_chart(
        bar_chart(
            item_summary,
            "Claim Amount",
            "Item Description",
            f"Top {len(item_summary)} Items by Claim Cost",
            x_format="$,.0f",
        ),
        width="stretch",
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Top Claimed Items")
        st.dataframe(item_summary, width="stretch", hide_index=True)
    with right:
        st.subheader("Defective and Damaged Items")
        st.dataframe(damage_summary, width="stretch", hide_index=True)

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
