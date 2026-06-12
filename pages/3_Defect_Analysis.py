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
    selected_value,
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
    _top_n_label = st.selectbox("Top rows shown", [10, 15, 20, 25, 30, 50, 75, 100, "All"], index=1)
    top_n = None if _top_n_label == "All" else _top_n_label

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

with st.expander("Formulas & Methodology"):
    st.markdown("""
**How weight comparisons work**

Each row in the source file is one weight measurement taken by an inspector. The source file also contains an expected weight (either a single target value or a low–high range) for each assembly item and work order. The dashboard computes the following fields for every row:

| Field | How it is calculated |
|---|---|
| Variance | *Actual Weight − Expected Target.* Positive = product is heavier than expected. Negative = product is lighter than expected. Zero = exactly on target. |
| Absolute Variance | The size of the error regardless of direction: \|Actual Weight − Expected Target\|. A measurement that is 0.5 oz over and one that is 0.5 oz under both produce an Absolute Variance of 0.5. This is the main accuracy indicator because it doesn't let over- and under-measurements cancel each other out. |
| Weight Status | **Within Range** — actual weight falls inside the tolerance band (low to high). **Below Range / Below Expected** — actual is below the lower boundary or below a single target. **Above Range / Above Expected** — actual is above the upper boundary or above a single target. **Expected Unknown** — the expected weight field was blank or could not be parsed, so no comparison is possible. |

A measurement is **comparable** only when the expected weight could be read from the source file. Rows flagged as "Expected Unknown" are counted in the totals but excluded from all variance calculations.

---

**Metric Cards**

| Metric | How it is calculated |
|---|---|
| Avg Variance | Sum of all (Actual − Expected) values for comparable measurements ÷ count. Because positive and negative errors cancel, this can read near zero even when there is heavy variation. A value close to zero does **not** mean the process is accurate — use Avg Abs Variance for that. |
| Avg Abs Variance | Sum of all \|Actual − Expected\| values for comparable measurements ÷ count. This is the primary accuracy metric. It tells you the typical size of the error across all measurements. |
| Max Abs Variance | The single largest \|Actual − Expected\| value in the filtered set — the worst individual measurement recorded. |
| Within Range | Count of measurements where the actual weight fell inside the defined tolerance band. |
| Below Expected | Count of measurements where the actual weight was below the expected target or tolerance floor. |
| Above Expected | Count of measurements where the actual weight was above the expected target or tolerance ceiling. |

---

**Charts**

| Chart | How it is calculated |
|---|---|
| Measured vs Expected (scatter) | Each dot is one measurement. X-axis = the expected target weight; Y-axis = the actual weight recorded by the inspector. The dashed diagonal line represents perfect accuracy — a dot exactly on the line means Actual = Expected (zero error). Dots above the line are heavier than expected; dots below are lighter. Clusters far from the diagonal reveal a consistent bias. Color shows the Weight Status of each measurement. |
| Avg Absolute Variance by Period | For each period (day/week/month), takes all comparable measurements that fall in that period and calculates the average \|Actual − Expected\|. A rising trend means inspections are becoming less consistent over time. |
| Work Orders by Avg Abs Variance | For each work order, calculates the average \|Actual − Expected\| across all its measurements and ranks from highest to lowest. Work orders at the top of the list are the most inconsistent production runs. Click a bar to list that work order's individual measurements below the chart. |
| Assembly Items by Avg Abs Variance | Same calculation as Work Orders above, but grouped by Assembly Item instead. Shows which products are most consistently missing their weight targets. Click a bar to list that item's individual measurements below the chart. |
""")

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
        wo_event = st.altair_chart(
            bar_chart(
                chart_data,
                "Average Absolute Variance",
                "Work Order Label",
                f"Top {len(chart_data)} Work Orders by Average Absolute Variance — click a bar to filter",
                color=CHART_ORANGE,
                selectable=True,
            ),
            width="stretch",
            on_select="rerun",
            key="defect_wo_chart",
        )
        st.dataframe(work_order_summary, width="stretch", hide_index=True)

        selected_label = selected_value(wo_event, "Work Order Label")
        raw_columns = [
            "Date", "Inspector", "Assembly Item", "Work Order", "Expected Weight",
            "Actual Weight", "Variance", "Absolute Variance", "Weight Status",
        ]
        if selected_label:
            sel_item, _, sel_wo = selected_label.partition(" | ")
            wo_rows = filtered[
                (filtered["Assembly Item"].astype(str) == sel_item)
                & (filtered["Work Order"].astype(str) == sel_wo)
            ]
            st.subheader(f"Measurements — {selected_label} ({len(wo_rows)} rows)")
            st.caption("Click the same bar again to clear.")
            st.dataframe(
                wo_rows.sort_values(["Date", "Source Row"])[
                    [c for c in raw_columns if c in wo_rows.columns]
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("Click a bar above to list that work order's individual measurements here.")

with tab_items:
    item_summary = weight_item_summary(filtered, limit=top_n)
    item_event = None
    if item_summary.empty:
        st.info("No assembly item measurements match the selected filters.")
    else:
        item_event = st.altair_chart(
            bar_chart(
                item_summary,
                "Average Absolute Variance",
                "Assembly Item",
                f"Top {len(item_summary)} Assembly Items by Average Absolute Variance — click a bar to filter",
                color=CHART_BLUE,
                selectable=True,
            ),
            width="stretch",
            on_select="rerun",
            key="defect_item_chart",
        )

    inspector_summary = weight_inspector_summary(filtered)
    left, right = st.columns(2)
    with left:
        st.subheader("Assembly Item Summary")
        st.dataframe(item_summary, width="stretch", hide_index=True)
    with right:
        st.subheader("Inspector Summary")
        st.dataframe(inspector_summary, width="stretch", hide_index=True)

    selected_item = selected_value(item_event, "Assembly Item")
    raw_columns = [
        "Date", "Inspector", "Assembly Item", "Work Order", "Expected Weight",
        "Actual Weight", "Variance", "Absolute Variance", "Weight Status",
    ]
    if selected_item:
        item_rows = filtered[filtered["Assembly Item"].astype(str) == selected_item]
        st.subheader(f"Measurements — {selected_item} ({len(item_rows)} rows)")
        st.caption("Click the same bar again to clear.")
        st.dataframe(
            item_rows.sort_values(["Date", "Work Order", "Source Row"])[
                [c for c in raw_columns if c in item_rows.columns]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Click a bar above to list that assembly item's individual measurements here.")

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
