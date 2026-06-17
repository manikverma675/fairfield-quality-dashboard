import altair as alt
import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    filter_by_date,
    scrap_item_summary,
    scrap_item_trend,
    scrap_summary,
    scrap_trend,
)
from quality_dashboard.config import SCRAP_FILE
from quality_dashboard.data_loaders import load_scrap_data
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
def cached_scrap() -> pd.DataFrame:
    return load_scrap_data(SCRAP_FILE)


if not SCRAP_FILE.exists():
    file_missing(SCRAP_FILE)

scrap = cached_scrap()
if scrap.empty:
    empty_state("No scrap transaction records were found in the source file.")

render_header(
    "Scrap Analysis",
    "Confirmed scrap — negative inventory adjustments in quarantine — by item, period, and transaction.",
    SCRAP_FILE.name,
)

# Every measure on this page is confirmed scrap: units written off via negative Inventory
# Adjustments in the quarantine location. load_scrap_data already applies that filter.
measure_col = "Confirmed Scrap"
min_date, max_date = date_bounds(scrap, "Date")
items = sorted(scrap["Item"].dropna().unique())
locations = sorted(scrap["Location"].dropna().unique()) if "Location" in scrap else []

with st.sidebar:
    st.header("Filters")
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
    _top_n_label = st.selectbox("Top items shown", [10, 15, 20, 25, 30, 50, 75, 100, "All"], index=1)
    top_n = None if _top_n_label == "All" else _top_n_label

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
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Scrap (units)", format_number(summary["confirmed_scrap"]))
col2.metric("Scrap Transactions", f"{summary['transactions']:,}")
col3.metric("Items Scrapped", f"{summary['items']:,}")
col4.metric("Largest Single Scrap (units)", format_number(summary["largest_event"]))
st.caption(
    "Scrap = units written off via a **negative Inventory Adjustment in the quarantine location**. "
    "Inventory Transfers (stock simply moved in or out of quarantine) are excluded — they are movement, not scrap. "
    "Confirmed Scrap is reported as a positive unit count (the magnitude of the negative adjustment). "
    "Every card, chart, and table on this page reflects only these confirmed-scrap transactions."
)

with st.expander("Formulas & Methodology"):
    st.markdown("""
**What counts as scrap**

Each row in the source file is one inventory transaction in the quarantine location. Most rows are **Inventory Transfers** — stock simply moved into or out of quarantine — and these are **not** scrap. A unit is only counted as scrap when it is **formally written off**, which in this data means:

> **Type = Inventory Adjustment**  **AND**  **Location = quarantine**  **AND**  **Quantity < 0**

`load_scrap_data` filters the file down to exactly those rows before anything on this page is calculated, so every card, chart, and table below reflects confirmed scrap only.

| Field | How it is calculated |
|---|---|
| Confirmed Scrap | The magnitude of the negative adjustment — `-Quantity` — reported as a **positive** count of units written off. This is the single measure used everywhere on the page. |

---

**Metric Cards**

| Metric | How it is calculated |
|---|---|
| Total Scrap (units) | Sum of Confirmed Scrap across every scrap transaction in the filtered date and item range. |
| Scrap Transactions | Number of confirmed-scrap transaction rows after filtering. |
| Items Scrapped | Count of distinct item codes that were scrapped at least once in the filtered set. |
| Largest Single Scrap (units) | The biggest single confirmed-scrap transaction in the filtered set. |

---

**Trend Charts**

| Chart | How it is calculated |
|---|---|
| Confirmed Scrap by Period | For each period (week/month/etc.), sums the confirmed-scrap units. Shows how scrap volume changes over time, with a 4-period rolling average. |

---

**Items Tab**

| Chart | How it is calculated |
|---|---|
| Item Trend | For each scrapped item, sums its confirmed-scrap units per period and draws a separate line. |
| Top Items | Sums confirmed-scrap units per item across the filtered range and ranks highest to lowest. The dropdown controls how many appear — select **All** to show every item. **Click a bar to list that item's individual write-off transactions in a table below.** |
""")

items_out = filtered

tab_trend, tab_items, tab_records = st.tabs(["Trend", "Items", "Records"])

with tab_trend:
    trend = scrap_trend(filtered, grain, measure_col)
    latest = trend.iloc[-1]
    peak = trend.loc[trend[measure_col].idxmax()]
    m1, m2, m3 = st.columns(3)
    m1.metric("Latest Period", format_number(latest[measure_col]))
    m2.metric("Peak Period", format_number(peak[measure_col]), peak["Period"].strftime("%Y-%m-%d"))
    m3.metric("Average per Period", format_number(trend[measure_col].mean()))

    trend_event = st.altair_chart(
        period_line_chart(
            trend,
            measure_col,
            f"{measure_col} by {grain.lower()} period — click a dot to drill down",
            color=CHART_BLUE,
            height=620,
            selectable=True,
            extra_tooltips=[
                alt.Tooltip("Transactions:Q", format=","),
                alt.Tooltip("Items:Q", format=","),
            ],
        ),
        width="stretch",
        on_select="rerun",
        key="scrap_trend_chart",
    )

    _GRAIN_DELTA = {
        "Daily": pd.Timedelta(days=1),
        "Weekly": pd.Timedelta(weeks=1),
        "Monthly": pd.DateOffset(months=1),
        "Quarterly": pd.DateOffset(months=3),
        "Yearly": pd.DateOffset(years=1),
    }

    selected_period_raw = selected_value(trend_event, "Period")
    if selected_period_raw is not None:
        # Altair returns temporal fields as UTC milliseconds (int) or ISO strings
        if isinstance(selected_period_raw, (int, float)):
            selected_ts = pd.Timestamp(int(selected_period_raw), unit="ms")
        else:
            selected_ts = pd.Timestamp(selected_period_raw)
        selected_ts = selected_ts.tz_localize(None) if selected_ts.tzinfo else selected_ts

        # Use date-range filter to avoid exact Timestamp equality issues
        delta = _GRAIN_DELTA.get(grain, pd.Timedelta(weeks=1))
        period_end = selected_ts + delta
        period_rows = filtered[
            (filtered["Date"] >= selected_ts) & (filtered["Date"] < period_end)
        ]
        drill_cols = ["Date", "Document Number", "Type", "Item", "Quantity",
                      "Confirmed Scrap", "Location", "Bin Number", "User", "Employee"]
        st.subheader(f"Transactions — {selected_ts.strftime('%Y-%m-%d')} ({len(period_rows):,} rows)")
        st.caption("Click the same dot again to clear.")
        st.dataframe(
            period_rows.sort_values("Date", ascending=False)[
                [c for c in drill_cols if c in period_rows.columns]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Click a dot on the chart to see that period's raw transactions.")


with tab_items:
    items_measure = "Confirmed Scrap"
    item_summary = scrap_item_summary(items_out, items_measure, limit=top_n)
    trend_items = selected_items if selected_items else item_summary["Item"].tolist()
    item_trend = scrap_item_trend(items_out, grain, items_measure, trend_items)

    if not item_trend.empty:
        item_chart = (
            alt.Chart(item_trend)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X("Period:T", title=None),
                y=alt.Y(f"{items_measure}:Q", title=items_measure),
                color=alt.Color("Item:N", title="Item"),
                tooltip=[
                    alt.Tooltip("Period:T", title="Period"),
                    alt.Tooltip("Item:N"),
                    alt.Tooltip(f"{items_measure}:Q", format=",.2f"),
                    alt.Tooltip("Transactions:Q", format=","),
                ],
            )
            .properties(title="Item Trend", height=380)
        )
        st.altair_chart(item_chart, width="stretch")

    item_event = st.altair_chart(
        bar_chart(
            item_summary,
            items_measure,
            "Item",
            f"Top {len(item_summary)} Items by {items_measure} — click a bar to filter",
            color=CHART_ORANGE,
            selectable=True,
        ),
        width="stretch",
        on_select="rerun",
        key="scrap_item_chart",
    )
    st.subheader("Item Summary")
    st.dataframe(item_summary, width="stretch", hide_index=True)

    selected_item = selected_value(item_event, "Item")
    raw_columns = [
        "Date",
        "Document Number",
        "Type",
        "Item",
        "Quantity",
        "Confirmed Scrap",
        "Location",
        "Bin Number",
        "User",
        "Employee",
    ]
    if selected_item:
        item_rows = items_out[items_out["Item"] == selected_item]
        st.subheader(f"Confirmed Scrap transactions — {selected_item} ({len(item_rows)} rows)")
        st.caption("Click the same bar again to clear.")
        st.dataframe(
            item_rows.sort_values("Date", ascending=False)[
                [c for c in raw_columns if c in item_rows.columns]
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("Click a bar above to list that item's confirmed-scrap transactions here.")

with tab_records:
    visible_columns = [
        "Date",
        "Document Number",
        "Type",
        "Item",
        "Quantity",
        "Confirmed Scrap",
        "Location",
        "Bin Number",
        "User",
        "Employee",
        "Inventory Number",
    ]
    visible_columns = [column for column in visible_columns if column in items_out.columns]
    st.dataframe(
        items_out.sort_values("Date", ascending=False)[visible_columns],
        width="stretch",
        hide_index=True,
    )
