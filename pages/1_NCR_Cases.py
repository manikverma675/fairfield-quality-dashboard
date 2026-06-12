import altair as alt
import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    filter_by_date,
    filter_ncr_profile,
    ncr_closure_trend,
    ncr_company_summary,
    ncr_status_summary,
    ncr_status_trend,
    ncr_summary,
    open_case_aging,
)
from quality_dashboard.config import NCR_CASES_FILE, OPEN_STATUSES
from quality_dashboard.data_loaders import load_ncr_cases
from quality_dashboard.metrics import PERIOD_OPTIONS, date_bounds, format_number
from quality_dashboard.ui import (
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
col1.metric("FPC | NCR Cases", f"{summary['total']:,}")
col2.metric("Open Backlog", f"{summary['open']:,}")
col3.metric("Closed", f"{summary['closed']:,}")
col4.metric("Median Closure Days", format_number(summary["median_closure_days"]))
col5.metric("Avg Open Age Days", format_number(summary["avg_age_days"]))

with st.expander("Formulas & Methodology"):
    st.markdown("""
**Data scope:** Only rows where Profile = "FPC | NCR" are included. All sidebar filters (date range, status, assignee) narrow this set further.

---

**How Open vs. Closed is determined**

- A case is counted as **Open** when its *Status* = **"Escalated"**. This is the only status confirmed to belong to FPC | NCR active cases.
- A case is counted as **Closed** when its *Stage* = **"Closed"** and *Date Closed* is filled. The *Date Closed* field is used to calculate how long it took and when it was resolved.
- Cases with other status or stage values (e.g. Stage = "Open", Status = "In Progress", Status = "Paused") are not counted in either bucket.

---

**Metric Cards**

| Metric | How it is calculated |
|---|---|
| FPC \| NCR Cases | Count of every case in the FPC \| NCR profile that passes the active filters. One row = one case. |
| Open Backlog | Count of cases whose *Status* is Escalated. |
| Closed | Count of cases whose *Stage* = "Closed". |
| Median Closure Days | For every case where *Stage* = "Closed" and *Date Closed* is filled: *Date Closed − Date Created* gives the number of days it took to close. All those values are sorted and the middle one is chosen. Half of closed cases resolved faster than this number, half took longer. The median is used instead of an average so that a handful of very slow cases don't distort the result. |
| Avg Open Age Days | For every case whose *Status* = "Escalated": *Today − Date Created* gives how many days the case has been sitting open. This card shows the average of those ages. |

---

**Trend Charts**

| Chart | How it is calculated |
|---|---|
| NCRs Created by Period — by Status | Cases are grouped by the month/week/quarter their *Date Created* falls in and split by their current *Status*. Each status gets its own line. Only the two statuses confirmed for FPC \| NCR are shown: **Escalated** (active open cases) and **Closed**. |
| Median Closure Time by Period | Takes only cases where *Stage* = "Closed" and *Date Closed* is filled, groups them by the month/week/quarter their *Date Closed* falls in, and calculates the median closure days within each period. A rising line means it is taking longer to close cases over time. |
| NCR Cases by Status | Groups all filtered FPC \| NCR cases by their current *Status* and counts how many are in each. Only Escalated and Closed are shown, as those are the only statuses confirmed for this profile. |

---

**Backlog Charts**

| Chart | How it is calculated |
|---|---|
| Open NCR Aging | Looks only at cases with an open status (Escalated). For each, *Today − Date Created* is calculated. Cases are placed into six age buckets: **0–7 days** (just opened), **8–30 days** (recent), **31–60 days** (aging), **61–90 days** (old), **91–180 days** (very old), **181+ days** (critical). Taller bars mean more open cases in that age range. Click a bar to filter the table below to just those cases. |
| Top NCR Companies | Looks only at open (Escalated) cases and groups them by *Company*, counts how many open cases each company has, and displays the top N ranked from most to least. The slider in the sidebar controls how many companies appear. Click a bar to filter the open backlog table to just that company's cases. |
""")

tab_trend, tab_backlog, tab_records = st.tabs(["Trend", "Backlog", "Records"])

with tab_trend:
    status_trend = ncr_status_trend(filtered, grain)
    status_trend = status_trend[status_trend["Status"].isin({"Escalated", "Closed"})]
    closure_trend = ncr_closure_trend(filtered, grain)

    left, right = st.columns(2)
    with left:
        if status_trend.empty:
            st.info("No NCR cases match the selected filters.")
        else:
            status_line_chart = (
                alt.Chart(status_trend)
                .mark_line(point=True, strokeWidth=2.5)
                .encode(
                    x=alt.X("Period:T", title=None),
                    y=alt.Y("Cases:Q", title="Cases"),
                    color=alt.Color(
                        "Status:N",
                        title="Status",
                        legend=alt.Legend(orient="bottom"),
                    ),
                    tooltip=[
                        alt.Tooltip("Period:T", title="Period"),
                        alt.Tooltip("Status:N", title="Status"),
                        alt.Tooltip("Cases:Q", title="Cases", format=","),
                    ],
                )
                .properties(title=f"NCRs Created by {grain.lower()} period — by Status", height=340)
            )
            st.altair_chart(status_line_chart, width="stretch")
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
    status_summary = status_summary[status_summary["Status"].isin({"Escalated", "Closed"})]
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
    open_filtered = filtered[filtered["Status"].isin(OPEN_STATUSES)]
    left, right = st.columns(2)
    with left:
        aging = open_case_aging(open_filtered)
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
        companies = ncr_company_summary(open_filtered, limit=top_n)
        company_event = st.altair_chart(
            bar_chart(companies, "Cases", "Company", f"Top {len(companies)} NCR Companies — click a bar to filter", selectable=True),
            width="stretch",
            on_select="rerun",
            key="ncr_company_chart",
        )

    selected_bucket = None
    try:
        points = aging_event.selection.get("sel", [])
        if points:
            selected_bucket = str(points[0]["Age Bucket"])
    except (AttributeError, KeyError, TypeError, IndexError):
        pass

    selected_company = None
    try:
        points = company_event.selection.get("sel", [])
        if points:
            selected_company = str(points[0]["Company"])
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
    open_cases = open_filtered.sort_values("Age Days", ascending=False)

    if selected_bucket and selected_bucket in BUCKET_RANGES:
        lo, hi = BUCKET_RANGES[selected_bucket]
        open_cases = open_cases[
            (open_cases["Age Days"] >= lo) & (open_cases["Age Days"] <= hi)
        ]
        label = f"Open NCR Backlog — {selected_bucket} days ({len(open_cases)} cases)"
        deselect_hint = "Click the same bar again to deselect."
    elif selected_company:
        open_cases = open_cases[open_cases["Company"] == selected_company]
        label = f"Open NCR Backlog — {selected_company} ({len(open_cases)} cases)"
        deselect_hint = "Click the same bar again to deselect."
    else:
        label = f"Open NCR Backlog ({len(open_cases)} cases)"
        deselect_hint = None

    st.subheader(label)
    if deselect_hint:
        st.caption(deselect_hint)
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

