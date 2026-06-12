import altair as alt
import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    filter_by_date,
    filter_ncr_profile,
    ncr_closure_trend,
    ncr_company_summary,
    ncr_created_trend,
    ncr_status_summary,
    ncr_summary,
    open_case_aging,
)
from quality_dashboard.config import NCR_CASES_FILE
from quality_dashboard.data_loaders import load_ncr_cases
from quality_dashboard.metrics import PERIOD_OPTIONS, date_bounds, format_number
from quality_dashboard.ui import (
    CHART_BLUE,
    CHART_ORANGE,
    CHART_RED,
    bar_chart,
    empty_state,
    file_missing,
    period_line_chart,
    render_header,
)




@st.cache_data(show_spinner=False)
def cached_cases() -> pd.DataFrame:
    return load_ncr_cases(NCR_CASES_FILE)


if not NCR_CASES_FILE.exists():
    file_missing(NCR_CASES_FILE)

cases = filter_ncr_profile(cached_cases(), "FPC | NCR")
if cases.empty:
    empty_state("No NCR cases were found in the source file.")

render_header(
    "NCR Cases",
    "Backlog, aging, closure time, and NCR case movement.",
    NCR_CASES_FILE.name,
)

min_date, max_date = date_bounds(cases, "Date Created")
statuses = sorted(cases["Status"].dropna().unique())
assignees = sorted([value for value in cases["Assigned To"].dropna().unique() if value])

with st.sidebar:
    st.header("Filters")
    grain = st.segmented_control("Period", PERIOD_OPTIONS, default="Monthly")
    selected_dates = st.date_input(
        "Created date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    selected_statuses = st.multiselect("Status", statuses, default=[])
    selected_assignees = st.multiselect("Assigned to", assignees, default=[])
    top_n = st.slider("Top companies shown", 5, 25, 12)

if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    start_date, end_date = min_date, max_date

filtered = filter_by_date(cases, "Date Created", start_date, end_date)
if selected_statuses:
    filtered = filtered[filtered["Status"].isin(selected_statuses)]
if selected_assignees:
    filtered = filtered[filtered["Assigned To"].isin(selected_assignees)]
if filtered.empty:
    empty_state("No NCR cases match the selected filters.")

summary = ncr_summary(filtered)
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("NCR Cases", f"{summary['total']:,}")
col2.metric("Open Backlog", f"{summary['open']:,}")
col3.metric("Closed", f"{summary['closed']:,}")
col4.metric("Median Closure Days", format_number(summary["median_closure_days"]))
col5.metric("Avg Open Age Days", format_number(summary["avg_age_days"]))

with st.expander("Formulas & Methodology"):
    st.markdown("""
**Metric Cards**
| Metric | Formula |
|---|---|
| NCR Cases | COUNT of all NCR cases matching the selected filters |
| Open Backlog | COUNT of cases where *Date Closed* is blank |
| Closed | COUNT of cases where *Date Closed* is filled |
| Median Closure Days | MEDIAN(*Closure Days*) for closed cases in the filtered set |
| Avg Open Age Days | AVERAGE(*Age Days*) for open cases (no close date) |

**Trend Charts**
| Chart | Formula |
|---|---|
| NCRs Created by Period | COUNT of cases grouped by *Date Created*, bucketed into the selected period grain |
| Median Closure Time by Period | MEDIAN(*Closure Days*) for cases whose *Date Closed* falls in each period |
| NCR Cases by Status | COUNT of cases grouped by *Status* value |

**Backlog Charts**
| Chart | Formula |
|---|---|
| Open NCR Aging | Open cases bucketed by *Age Days*: 0–7 · 8–30 · 31–60 · 61–90 · 91–180 · 181+ days |
| Top NCR Companies | COUNT of cases grouped by *Company*, ranked descending — top N controlled by the slider |

**Data scope:** Profile = "FPC | NCR". *Age Days* and *Closure Days* are computed in the source file (today − Date Created / Date Closed − Date Created).
""")

tab_trend, tab_backlog, tab_records = st.tabs(["Trend", "Backlog", "Records"])

with tab_trend:
    created_trend = ncr_created_trend(filtered, grain)
    closure_trend = ncr_closure_trend(filtered, grain)

    left, right = st.columns(2)
    with left:
        st.altair_chart(
            period_line_chart(
                created_trend,
                "Created Cases",
                f"NCRs Created by {grain.lower()} period",
                color=CHART_BLUE,
                extra_tooltips=[
                    alt.Tooltip("Open Cases:Q", format=","),
                    alt.Tooltip("Closed Cases:Q", format=","),
                ],
            ),
            width="stretch",
        )
    with right:
        if closure_trend.empty:
            st.info("No closed NCRs match the selected filters.")
        else:
            st.altair_chart(
                period_line_chart(
                    closure_trend,
                    "Median Closure Days",
                    f"Median Closure Time by {grain.lower()} period",
                    color=CHART_ORANGE,
                    extra_tooltips=[alt.Tooltip("Closed Cases:Q", format=",")],
                ),
                width="stretch",
            )

    status_summary = ncr_status_summary(filtered)
    st.altair_chart(
        bar_chart(status_summary, "Cases", "Status", "NCR Cases by Status", color=CHART_RED),
        width="stretch",
    )

BUCKET_RANGES = {
    "0-7":    (0,   7),
    "8-30":   (8,   30),
    "31-60":  (31,  60),
    "61-90":  (61,  90),
    "91-180": (91,  180),
    "181+":   (181, float("inf")),
}

with tab_backlog:
    left, right = st.columns(2)
    with left:
        aging = open_case_aging(filtered)
        if aging.empty:
            st.info("No open NCR backlog in the selected filters.")
            aging_event = None
        else:
            aging_event = st.altair_chart(
                bar_chart(aging, "Cases", "Age Bucket", "Open NCR Aging — click a bar to filter", color=CHART_ORANGE, selectable=True),
                width="stretch",
                on_select="rerun",
                key="ncr_aging_chart",
            )
    with right:
        companies = ncr_company_summary(filtered, limit=top_n)
        st.altair_chart(
            bar_chart(companies, "Cases", "Company", f"Top {len(companies)} NCR Companies"),
            width="stretch",
        )

    selected_bucket = None
    try:
        points = aging_event.selection.get("sel", [])
        if points:
            selected_bucket = str(points[0]["Age Bucket"])
    except (AttributeError, KeyError, TypeError, IndexError):
        pass

    open_columns = [
        "Number",
        "Date Created",
        "Age Days",
        "Status",
        "Assigned To",
        "Company",
        "Subject",
        "Item",
    ]
    open_cases = filtered[filtered["Date Closed"].isna()].sort_values("Age Days", ascending=False)

    if selected_bucket and selected_bucket in BUCKET_RANGES:
        lo, hi = BUCKET_RANGES[selected_bucket]
        open_cases = open_cases[
            (open_cases["Age Days"] >= lo) & (open_cases["Age Days"] <= hi)
        ]
        st.subheader(f"Open NCR Backlog — {selected_bucket} days ({len(open_cases)} cases)")
        st.caption("Click the same bar again to deselect.")
    else:
        st.subheader(f"Open NCR Backlog ({len(open_cases)} cases)")

    st.dataframe(open_cases[open_columns], width="stretch", hide_index=True)

with tab_records:
    visible_columns = [
        "Number",
        "Status",
        "Stage",
        "Date Created",
        "Date Closed",
        "Closure Days",
        "Age Days",
        "Company",
        "Assigned To",
        "Subject",
        "Item",
        "Type",
    ]
    visible_columns = [column for column in visible_columns if column in filtered.columns]
    st.dataframe(
        filtered.sort_values("Date Created", ascending=False)[visible_columns],
        width="stretch",
        hide_index=True,
    )

