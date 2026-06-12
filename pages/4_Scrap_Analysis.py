import altair as alt
import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    filter_by_date,
    scrap_item_summary,
    scrap_item_trend,
    scrap_rate_trend,
    scrap_summary,
    scrap_trend,
)
from quality_dashboard.config import SCRAP_FILE
from quality_dashboard.data_loaders import load_scrap_data
from quality_dashboard.metrics import PERIOD_OPTIONS, date_bounds, format_number, format_percent
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
def cached_scrap() -> pd.DataFrame:
    return load_scrap_data(SCRAP_FILE)


if not SCRAP_FILE.exists():
    file_missing(SCRAP_FILE)

scrap = cached_scrap()
if scrap.empty:
    empty_state("No scrap transaction records were found in the source file.")

render_header(
    "Scrap Analysis",
    "Quarantine production reject movement by item, period, and transaction.",
    SCRAP_FILE.name,
)

measure_options = ["Confirmed Scrap", "Into Quarantine", "Quarantine Balance", "Absolute Movement"]
min_date, max_date = date_bounds(scrap, "Date")
items = sorted(scrap["Item"].dropna().unique())
locations = sorted(scrap["Location"].dropna().unique()) if "Location" in scrap else []

with st.sidebar:
    st.header("Filters")
    measure_col = st.radio("Scrap measure", measure_options, index=0)
    grain = st.segmented_control("Period", PERIOD_OPTIONS, default="Weekly")
    selected_dates = st.date_input(
        "Transaction date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    selected_items = st.multiselect("Include items", items, default=[])
    excluded_items = st.multiselect("Exclude items", items, default=[])
    selected_locations = st.multiselect("Location", locations, default=[])
    top_n = st.slider("Top items shown", 5, 30, 15)

if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    start_date, end_date = min_date, max_date

filtered = filter_by_date(scrap, "Date", start_date, end_date)
if selected_items:
    filtered = filtered[filtered["Item"].isin(selected_items)]
if excluded_items:
    filtered = filtered[~filtered["Item"].isin(excluded_items)]
if selected_locations and "Location" in filtered:
    filtered = filtered[filtered["Location"].isin(selected_locations)]
if filtered.empty:
    empty_state("No scrap records match the selected filters.")

summary = scrap_summary(filtered, measure_col)
rate_trend = scrap_rate_trend(filtered, grain)
latest_rate = rate_trend.iloc[-1] if not rate_trend.empty else None
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Confirmed Scrap", format_number(summary["confirmed_scrap"]))
col2.metric("Into Quarantine", format_number(summary["into_quarantine"]))
col3.metric("Quarantine Balance", format_number(summary["quarantine_balance"]))
col4.metric(
    "Confirmation Rate",
    format_percent(latest_rate["Scrap Confirmation Rate"] if latest_rate is not None else float("nan")),
)
col5.metric("Items", f"{summary['items']:,}")
col6.metric("Transactions", f"{summary['transactions']:,}")
st.caption(
    "Confirmed Scrap = units formally written off as waste (negative-quantity transactions only). "
    "Into Quarantine = units moved into the quarantine location (positive-quantity transactions). "
    "Quarantine Balance = Into − Confirmed; includes both pending-discard units AND non-waste items "
    "that permanently live in quarantine (e.g. RFID tags) — not all balance is true scrap risk. "
    "Confirmation Rate = Confirmed Scrap / Into Quarantine for the latest period."
)

with st.expander("Formulas & Methodology"):
    st.markdown("""
**How the quarantine flow works**

Each row in the source file is one inventory transaction. When a unit is suspected defective it is moved into a quarantine location (positive quantity). When it is formally written off it exits quarantine as confirmed scrap (negative quantity). The dashboard derives four measures from the raw quantity field:

| Field | How it is calculated |
|---|---|
| Into Quarantine | Units moved **into** quarantine — the positive-quantity transactions only. These are units pulled from normal inventory because something looked wrong. |
| Confirmed Scrap | Units **written off** as waste — the absolute value of the negative-quantity transactions. These are units that have been permanently discarded after review. |
| Quarantine Balance | *Into Quarantine − Confirmed Scrap* summed per item. The balance is made up of **two very different populations**: (1) products with a pending discard decision — units flagged as defective that have not yet been formally written off; and (2) items that live in the quarantine location permanently and are **not** waste (for example, RFID tags that are stored there as part of normal operations and are never expected to be scrapped). Because of the second group, a high or growing Quarantine Balance does not always mean a quality problem — it may simply reflect non-scrap items accumulating in the quarantine bin. Only items that have at least one negative-quantity transaction (a confirmed scrap write-off) can be treated as true scrap candidates. |
| Absolute Movement | \|Quantity\| for every transaction regardless of direction. Useful for measuring total activity volume when you don't care about the in-vs-out split. |

---

**Metric Cards**

| Metric | How it is calculated |
|---|---|
| Confirmed Scrap | Sum of all confirmed-scrap units across every transaction in the filtered date and item range. |
| Into Quarantine | Sum of all units moved into quarantine in the filtered range. |
| Quarantine Balance | Sum of (Into Quarantine − Confirmed Scrap) across the filtered transactions. This number includes both true pending-discard units **and** non-waste items that permanently reside in the quarantine location (e.g. RFID tags). Interpret it alongside Confirmed Scrap rather than in isolation. |
| Confirmation Rate | *Confirmed Scrap ÷ Into Quarantine*, calculated using only the numbers from the **most recent period** on the chart. Tells you what fraction of quarantined units are actually being written off as scrap right now. A rate below 1.0 means more units are going in than are being resolved. |
| Items | Count of distinct item codes that appear in at least one transaction in the filtered set. |
| Transactions | Total number of individual transaction rows after filtering. |

---

**Trend Charts**

| Chart | How it is calculated |
|---|---|
| Selected Measure by Period | For each period (week/month/etc.), sums whichever measure you selected in the sidebar radio button. Shows how that measure changes over time. |
| Cumulative Confirmed Scrap vs Into Quarantine | Running totals of both flows from the start of the selected date range. The gap where blue (Into Quarantine) sits above orange (Confirmed Scrap) is the outstanding quarantine balance — units flagged but not yet written off. Data goes back to September 2022 so the full quarantine history is captured. |

---

**Items Tab**

| Chart | How it is calculated |
|---|---|
| Item Trend | Shows only items whose net *Quarantine Balance* (Into Quarantine − Confirmed Scrap, summed across all their transactions) is **negative** — meaning more units were taken out of inventory as scrap than were ever put into quarantine. For each of those items, the chosen measure is summed per period and drawn as a separate line. |
| Top Items | Same negative-balance filter as Item Trend. Items where the net balance is zero or positive (more units going in than coming out) are excluded. The remaining items are ranked from highest to lowest by the chosen measure. The slider controls how many appear. |

*Note: Quarantine Balance can show as negative for a period if more units were confirmed scrap than entered quarantine in that same period — this happens when older quarantine stock is cleared in bulk.*
""")

tab_trend, tab_items, tab_records = st.tabs(["Trend", "Items", "Records"])

with tab_trend:
    trend = scrap_trend(filtered, grain, measure_col)
    left, right = st.columns([2, 1])
    with left:
        st.altair_chart(
            period_line_chart(
                trend,
                measure_col,
                f"{measure_col} by {grain.lower()} period",
                color=CHART_BLUE,
                extra_tooltips=[
                    alt.Tooltip("Transactions:Q", format=","),
                    alt.Tooltip("Items:Q", format=","),
                ],
            ),
            width="stretch",
        )
    with right:
        latest = trend.iloc[-1]
        peak = trend.loc[trend[measure_col].idxmax()]
        st.metric("Latest Period", format_number(latest[measure_col]))
        st.metric("Peak Period", format_number(peak[measure_col]), peak["Period"].strftime("%Y-%m-%d"))
        st.metric("Average per Period", format_number(trend[measure_col].mean()))

    if not rate_trend.empty:
        cumulative = rate_trend[["Period", "Confirmed Scrap", "Into Quarantine"]].copy()
        cumulative["Confirmed Scrap"] = cumulative["Confirmed Scrap"].cumsum()
        cumulative["Into Quarantine"] = cumulative["Into Quarantine"].cumsum()
        cumulative_data = cumulative.melt(
            id_vars=["Period"],
            value_vars=["Confirmed Scrap", "Into Quarantine"],
            var_name="Flow",
            value_name="Units",
        )
        cumulative_chart = (
            alt.Chart(cumulative_data)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X("Period:T", title=None),
                y=alt.Y("Units:Q", title="Cumulative Units"),
                color=alt.Color(
                    "Flow:N",
                    scale=alt.Scale(
                        domain=["Confirmed Scrap", "Into Quarantine"],
                        range=[CHART_ORANGE, CHART_BLUE],
                    ),
                ),
                tooltip=[
                    alt.Tooltip("Period:T", title="Period"),
                    alt.Tooltip("Flow:N"),
                    alt.Tooltip("Units:Q", format=",.0f", title="Cumulative Units"),
                ],
            )
            .properties(
                title=f"Cumulative Confirmed Scrap vs Into Quarantine",
                height=300,
            )
        )
        st.altair_chart(cumulative_chart, width="stretch")
        st.caption(
            "Cumulative totals running from the start of the selected date range. "
            "When the orange (Confirmed Scrap) line rises above blue (Into Quarantine), "
            "it means those units were quarantined before the selected date range begins — "
            "their quarantine entry is not visible in this window but the scrap write-off is. "
            "The vertical gap where blue is above orange represents units still sitting in quarantine."
        )

with tab_items:
    item_balance = filtered.groupby("Item")["Quarantine Balance"].sum()
    negative_balance_items = set(item_balance[item_balance < 0].index)
    items_out = filtered[filtered["Item"].isin(negative_balance_items)]

    item_summary = scrap_item_summary(items_out, measure_col, limit=top_n)
    trend_items = selected_items if selected_items else item_summary["Item"].tolist()
    item_trend = scrap_item_trend(items_out, grain, measure_col, trend_items)

    if not item_trend.empty:
        item_chart = (
            alt.Chart(item_trend)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X("Period:T", title=None),
                y=alt.Y(f"{measure_col}:Q", title=measure_col),
                color=alt.Color("Item:N", title="Item"),
                tooltip=[
                    alt.Tooltip("Period:T", title="Period"),
                    alt.Tooltip("Item:N"),
                    alt.Tooltip(f"{measure_col}:Q", format=",.2f"),
                    alt.Tooltip("Transactions:Q", format=","),
                ],
            )
            .properties(title="Item Trend", height=380)
        )
        st.altair_chart(item_chart, width="stretch")

    st.altair_chart(
        bar_chart(
            item_summary,
            measure_col,
            "Item",
            f"Top {len(item_summary)} Items by {measure_col}",
            color=CHART_ORANGE,
        ),
        width="stretch",
    )
    st.subheader("Item Summary")
    st.dataframe(item_summary, width="stretch", hide_index=True)

with tab_records:
    visible_columns = [
        "Date",
        "Document Number",
        "Type",
        "Item",
        "Quantity",
        "Into Quarantine",
        "Confirmed Scrap",
        "Absolute Movement",
        "Location",
        "Bin Number",
        "User",
        "Employee",
        "Inventory Number",
    ]
    visible_columns = [column for column in visible_columns if column in filtered.columns]
    st.dataframe(
        filtered.sort_values("Date", ascending=False)[visible_columns],
        width="stretch",
        hide_index=True,
    )
