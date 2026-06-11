import altair as alt
import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    filter_by_date,
    weight_inspector_summary,
    weight_item_summary,
    weight_summary,
    weight_trend,
    weight_work_order_summary,
)
from quality_dashboard.config import DEFECT_FILE
from quality_dashboard.data_loaders import load_defect_data
from quality_dashboard.metrics import PERIOD_OPTIONS, date_bounds, format_number
from quality_dashboard.ui import (
    CHART_BLUE,
    CHART_ORANGE,
    bar_chart,
    empty_state,
    file_missing,
    period_line_chart,
    render_header,
)




@st.cache_data(show_spinner=False, ttl=3600)
def cached_measurements() -> pd.DataFrame:
    return load_defect_data(DEFECT_FILE)


def expected_actual_chart(data: pd.DataFrame) -> alt.Chart:
    comparable = data.dropna(subset=["Expected Target", "Actual Weight"]).copy()
    if comparable.empty:
        return alt.Chart(pd.DataFrame({"message": ["No comparable measurements"]})).mark_text()

    lower = min(comparable["Expected Target"].min(), comparable["Actual Weight"].min())
    upper = max(comparable["Expected Target"].max(), comparable["Actual Weight"].max())
    reference = pd.DataFrame({"Expected Target": [lower, upper], "Actual Weight": [lower, upper]})

    points = (
        alt.Chart(comparable)
        .mark_circle(size=68, opacity=0.78)
        .encode(
            x=alt.X("Expected Target:Q", title="Expected Weight"),
            y=alt.Y("Actual Weight:Q", title="Measured Weight"),
            color=alt.Color("Weight Status:N", title="Status"),
            tooltip=[
                alt.Tooltip("Date:T"),
                alt.Tooltip("Assembly Item:N"),
                alt.Tooltip("Work Order:N"),
                alt.Tooltip("Inspector:N"),
                alt.Tooltip("Expected Weight:N"),
                alt.Tooltip("Tolerance:N"),
                alt.Tooltip("Expected Target:Q", format=",.3f"),
                alt.Tooltip("Actual Weight:Q", format=",.3f"),
                alt.Tooltip("Variance:Q", format=",.3f"),
                alt.Tooltip("Weight Status:N"),
            ],
        )
    )
    diagonal = (
        alt.Chart(reference)
        .mark_line(color="#64748b", strokeDash=[6, 4], strokeWidth=2)
        .encode(x="Expected Target:Q", y="Actual Weight:Q")
    )
    return (diagonal + points).properties(title="Measured Weight vs Expected Weight", height=430)


if not DEFECT_FILE.exists():
    file_missing(DEFECT_FILE)

measurements = cached_measurements()
if measurements.empty:
    empty_state("No weight inspection measurements were found in the source file.")

render_header(
    "Weight Inspection Analysis",
    "Measured inspection weights compared with expected weights by assembly item and work order.",
    DEFECT_FILE.name,
)
st.caption(
    "Defect rate is not calculated here because the reported pass/fail columns do not "
    "reliably match the recorded weight measurements."
)

min_date, max_date = date_bounds(measurements, "Date")
inspectors = sorted([value for value in measurements["Inspector"].dropna().unique() if value])
items = sorted(measurements["Assembly Item"].dropna().unique())
work_orders = sorted([value for value in measurements["Work Order"].dropna().unique() if value])

with st.sidebar:
    st.header("Filters")
    grain = st.segmented_control("Variance period", PERIOD_OPTIONS, default="Daily")
    selected_dates = st.date_input(
        "Inspection date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    selected_inspectors = st.multiselect("Inspector", inspectors, default=[])
    selected_items = st.multiselect("Assembly item", items, default=[])
    selected_work_orders = st.multiselect("Work order", work_orders, default=[])
    top_n = st.slider("Top rows shown", 5, 50, 15)

if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    start_date, end_date = min_date, max_date

filtered = filter_by_date(measurements, "Date", start_date, end_date)
if selected_inspectors:
    filtered = filtered[filtered["Inspector"].isin(selected_inspectors)]
if selected_items:
    filtered = filtered[filtered["Assembly Item"].isin(selected_items)]
if selected_work_orders:
    filtered = filtered[filtered["Work Order"].isin(selected_work_orders)]
if filtered.empty:
    empty_state("No weight measurements match the selected filters.")

summary = weight_summary(filtered)
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Avg Variance", format_number(summary["average_variance"]))
col2.metric("Avg Abs Variance", format_number(summary["average_absolute_variance"]))
col3.metric("Max Abs Variance", format_number(summary["maximum_absolute_variance"]))
col4.metric("Within Range", f"{summary['within_range']:,}")
col5.metric("Below Expected", f"{summary['below_expected']:,}")
col6.metric("Above Expected", f"{summary['above_expected']:,}")
st.caption(
    f"Comparable measurements: {summary['comparable_measurements']:,} of "
    f"{summary['measurements']:,}. Expected unknown or unparsed: {summary['expected_unknown']:,}."
)

tab_compare, tab_work_orders, tab_items, tab_records = st.tabs(
    ["Expected vs Actual", "Work Orders", "Assembly Items", "Measurements"]
)

with tab_compare:
    comparable = filtered[filtered["Expected Target"].notna()]
    if comparable.empty:
        st.info("No parseable expected weights match the selected filters.")
    else:
        st.altair_chart(expected_actual_chart(comparable), width="stretch")

        trend = weight_trend(filtered, grain)
        if not trend.empty:
            if len(filtered["Assembly Item"].unique()) > 1:
                st.caption(
                    "Variance trend combines multiple assembly items. Filter to one item or work order "
                    "for the cleanest process view."
                )
            st.altair_chart(
                period_line_chart(
                    trend,
                    "Average Absolute Variance",
                    f"Average Absolute Variance by {grain.lower()} period",
                    color=CHART_BLUE,
                    extra_tooltips=[
                        alt.Tooltip("Comparable Measurements:Q", format=","),
                        alt.Tooltip("Average Variance:Q", format=",.3f"),
                        alt.Tooltip("Maximum Absolute Variance:Q", format=",.3f"),
                    ],
                ),
                width="stretch",
            )

with tab_work_orders:
    work_order_summary = weight_work_order_summary(filtered, limit=top_n)
    if work_order_summary.empty:
        st.info("No work order measurements match the selected filters.")
    else:
        chart_data = work_order_summary.copy()
        chart_data["Work Order Label"] = (
            chart_data["Assembly Item"].astype(str) + " | " + chart_data["Work Order"].astype(str)
        )
        st.altair_chart(
            bar_chart(
                chart_data,
                "Average Absolute Variance",
                "Work Order Label",
                f"Top {len(chart_data)} Work Orders by Average Absolute Variance",
                color=CHART_ORANGE,
            ),
            width="stretch",
        )
    st.dataframe(work_order_summary, width="stretch", hide_index=True)

with tab_items:
    item_summary = weight_item_summary(filtered, limit=top_n)
    if item_summary.empty:
        st.info("No assembly item measurements match the selected filters.")
    else:
        st.altair_chart(
            bar_chart(
                item_summary,
                "Average Absolute Variance",
                "Assembly Item",
                f"Top {len(item_summary)} Assembly Items by Average Absolute Variance",
                color=CHART_BLUE,
            ),
            width="stretch",
        )

    inspector_summary = weight_inspector_summary(filtered)
    left, right = st.columns(2)
    with left:
        st.subheader("Assembly Item Summary")
        st.dataframe(item_summary, width="stretch", hide_index=True)
    with right:
        st.subheader("Inspector Summary")
        st.dataframe(inspector_summary, width="stretch", hide_index=True)

with tab_records:
    visible_columns = [
        "Date",
        "Inspector",
        "Assembly Item",
        "Work Order",
        "Expected Weight",
        "Actual Weight",
        "Variance",
        "Absolute Variance",
        "Weight Status",
        "Comparison Low",
        "Comparison High",
        "Tolerance",
        "Measurement Slot",
        "Source Row",
    ]
    st.dataframe(
        filtered.sort_values(
            ["Date", "Assembly Item", "Work Order", "Source Row"],
            ascending=[False, True, True, True],
        )[visible_columns],
        width="stretch",
        hide_index=True,
    )
