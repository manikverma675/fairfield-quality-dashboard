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
    CHART_GREEN,
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
    "Confirmed Scrap = units that left quarantine as waste. "
    "Into Quarantine = units flagged as potential scrap. "
    "Quarantine Balance = units still sitting in quarantine (Into − Confirmed). "
    "Confirmation Rate = Confirmed Scrap / Into Quarantine for the latest period."
)

with st.expander("Formulas & Methodology"):
    st.markdown("""
**Field Definitions**
| Field | Definition |
|---|---|
| Confirmed Scrap | Units formally written off as waste — they left quarantine as scrap |
| Into Quarantine | Units flagged as suspect and moved into quarantine for review |
| Quarantine Balance | Into Quarantine − Confirmed Scrap (units still pending final disposition) |
| Absolute Movement | \|Quantity\| of each transaction regardless of direction (in or out) |

**Metric Cards**
| Metric | Formula |
|---|---|
| Confirmed Scrap | SUM(Confirmed Scrap) over filtered transactions |
| Into Quarantine | SUM(Into Quarantine) over filtered transactions |
| Quarantine Balance | SUM(Quarantine Balance) over filtered transactions |
| Confirmation Rate | Confirmed Scrap ÷ Into Quarantine — calculated for the **most recent period** only |
| Items | COUNT DISTINCT items appearing in filtered transactions |
| Transactions | COUNT of individual transaction rows |

**Trend Charts**
| Chart | Formula |
|---|---|
| Selected Measure by Period | SUM of the chosen measure (sidebar radio) grouped by the selected period grain |
| Rolling Average | 4-period rolling mean of the selected measure — uses `min_periods=1` so early periods are not blank |
| Confirmed Scrap vs Into Quarantine | Both series summed per period — Confirmed Scrap can exceed Into Quarantine in a period because items quarantined earlier may be confirmed later |

**Items Tab**
| Chart | Formula |
|---|---|
| Item Trend | SUM of chosen measure per item per period |
| Top Items | SUM of chosen measure per item, ranked descending — top N controlled by the slider |

*Note: Quarantine Balance can be negative in a period if more units were confirmed than entered quarantine that period (prior-period stock being cleared).*
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

    rolling = (
        alt.Chart(trend)
        .mark_line(color=CHART_GREEN, strokeDash=[6, 4], strokeWidth=3)
        .encode(
            x=alt.X("Period:T", title=None),
            y=alt.Y("Rolling Average:Q", title="4-period rolling average"),
            tooltip=[
                alt.Tooltip("Period:T", title="Period"),
                alt.Tooltip("Rolling Average:Q", format=",.2f"),
            ],
        )
        .properties(title="Rolling Average", height=260)
    )
    st.altair_chart(rolling, width="stretch")

    if not rate_trend.empty:
        flow_data = rate_trend.melt(
            id_vars=["Period"],
            value_vars=["Confirmed Scrap", "Into Quarantine"],
            var_name="Flow",
            value_name="Units",
        )
        flow_chart = (
            alt.Chart(flow_data)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X("Period:T", title=None),
                y=alt.Y("Units:Q", title="Units"),
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
                    alt.Tooltip("Units:Q", format=",.0f"),
                ],
            )
            .properties(
                title=f"Confirmed Scrap vs Into Quarantine by {grain.lower()} period",
                height=300,
            )
        )
        st.altair_chart(flow_chart, width="stretch")
        st.caption(
            "Confirmed Scrap can exceed Into Quarantine in a given period because items "
            "quarantined in earlier periods are often confirmed/disposed later. "
            "The overall rate in the headline card is the meaningful figure."
        )

with tab_items:
    item_summary = scrap_item_summary(filtered, measure_col, limit=top_n)
    trend_items = selected_items if selected_items else item_summary["Item"].tolist()
    item_trend = scrap_item_trend(filtered, grain, measure_col, trend_items)

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
