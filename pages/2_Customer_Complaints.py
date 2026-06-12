import pandas as pd
import streamlit as st

from quality_dashboard.calculations import (
    filter_by_date,
    filter_complaints,
    ncr_company_summary,
    ncr_created_trend,
    ncr_status_summary,
    ncr_summary,
    open_case_aging,
)
from quality_dashboard.config import NCR_CASES_FILE, OPEN_STATUSES
from quality_dashboard.data_loaders import load_ncr_cases
from quality_dashboard.metrics import PERIOD_OPTIONS, date_bounds, format_number
from quality_dashboard.ui import (
    CHART_BLUE,
    CHART_ORANGE,
    bar_chart,
    dual_line_chart,
    empty_state,
    file_missing,
    render_header,
)




@st.cache_data(show_spinner=False)
def cached_cases() -> pd.DataFrame:
    return load_ncr_cases(NCR_CASES_FILE)


if not NCR_CASES_FILE.exists():
    file_missing(NCR_CASES_FILE)

complaints = filter_complaints(cached_cases())
if complaints.empty:
    empty_state("No customer complaint cases were found in the source file.")

render_header(
    "Customer Complaints",
    "Customer support case trend, backlog, and closure movement.",
    NCR_CASES_FILE.name,
)

min_date, max_date = date_bounds(complaints, "Date Created")
statuses = sorted(complaints["Status"].dropna().unique())
companies = sorted([value for value in complaints["Company"].dropna().unique() if value])

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
    selected_companies = st.multiselect("Company", companies, default=[])
    _top_n_label = st.selectbox("Top companies shown", [10, 15, 20, 25, 30, 50, 75, 100, "All"], index=1)
    top_n = None if _top_n_label == "All" else _top_n_label

if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
else:
    start_date, end_date = min_date, max_date

filtered = filter_by_date(complaints, "Date Created", start_date, end_date)
if selected_statuses:
    filtered = filtered[filtered["Status"].isin(selected_statuses)]
if selected_companies:
    filtered = filtered[filtered["Company"].isin(selected_companies)]
if filtered.empty:
    empty_state("No customer complaints match the selected filters.")

summary = ncr_summary(filtered)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Complaints", f"{summary['total']:,}")
col2.metric("Open", f"{summary['open']:,}")
col3.metric("Closed", f"{summary['closed']:,}")
col4.metric("Median Closure Days", format_number(summary["median_closure_days"]))

with st.expander("Formulas & Methodology"):
    st.markdown("""
**What counts as a Customer Complaint?**

This page filters the NCR Cases file to only rows where **Profile = "FPC | NCR"** AND **Assigned To = "Sheri King"**. Every other NCR case is excluded. The sidebar filters (date range, status, company) narrow this set further.

---

**How Open vs. Closed is determined**

- A complaint is counted as **Open** when its *Status* = **"Escalated"**. This is the only status confirmed to belong to FPC | NCR active cases.
- A complaint is counted as **Closed** when its *Stage* = **"Closed"** and *Date Closed* is filled. The *Date Closed* field is used to calculate how long it took to resolve.
- Cases with other status or stage values are not counted in either bucket.

---

**Metric Cards**

| Metric | How it is calculated |
|---|---|
| Complaints | Count of every complaint row that passes the active filters. One row = one complaint case. |
| Open | Count of complaints whose *Status* is Escalated. |
| Closed | Count of complaints whose *Stage* = "Closed". |
| Median Closure Days | For every complaint where *Stage* = "Closed" and *Date Closed* is filled: *Date Closed − Date Created* gives the number of days it took to resolve. All those values are sorted and the middle one is chosen. Half of complaints were resolved faster than this number, half took longer. The median is used so that a few very slow cases don't skew the result. |

---

**Trend Charts**

| Chart | How it is calculated |
|---|---|
| Open / Closed by Period | Complaints are grouped by the month/week/quarter their *Date Created* falls in, then split into two lines: the orange line counts cases from that period whose current *Status* is still open (Escalated), and the blue line counts cases whose *Stage* = "Closed". Both lines track cases by when they were opened, not when they were closed. |
| Complaint Status | Groups all filtered complaints by their current *Status* value and counts how many are in each status. |
| Top Companies | Groups all filtered complaints by *Company*, counts how many complaints each company has generated, and ranks from most to least. The dropdown controls how many companies appear — select **All** to show every company. |

---

**Backlog**

| Chart | How it is calculated |
|---|---|
| Open Complaint Aging | Looks only at complaints whose *Status* is Escalated. For each, *Today − Date Created* is calculated. Each complaint is placed into one of six age buckets: **0–7 days** (just opened), **8–30 days** (recent), **31–60 days** (aging), **61–90 days** (old), **91–180 days** (very old), **181+ days** (critical). A taller bar means more unresolved complaints are sitting in that age range. |
""")

tab_trend, tab_backlog, tab_records = st.tabs(["Trend", "Backlog", "Records"])

with tab_trend:
    trend = ncr_created_trend(filtered, grain)
    st.altair_chart(
        dual_line_chart(
            trend,
            ["Open Cases", "Closed Cases"],
            f"Complaints by {grain.lower()} period",
            colors=[CHART_ORANGE, CHART_BLUE],
        ),
        width="stretch",
    )

    left, right = st.columns(2)
    with left:
        st.altair_chart(
            bar_chart(ncr_status_summary(filtered), "Cases", "Status", "Complaint Status"),
            width="stretch",
        )
    with right:
        company_summary = ncr_company_summary(filtered, limit=top_n)
        st.altair_chart(
            bar_chart(company_summary, "Cases", "Company", f"Top {len(company_summary)} Companies"),
            width="stretch",
        )

with tab_backlog:
    aging = open_case_aging(filtered)
    if aging.empty:
        st.info("No open customer complaint backlog in the selected filters.")
    else:
        st.altair_chart(
            bar_chart(aging, "Cases", "Age Bucket", "Open Complaint Aging", color=CHART_ORANGE),
            width="stretch",
        )

    open_columns = [
        "Number",
        "Date Created",
        "Age Days",
        "Status",
        "Company",
        "Subject",
        "Assigned To",
    ]
    st.dataframe(
        filtered[filtered["Status"].isin(OPEN_STATUSES)]
        .sort_values("Age Days", ascending=False)[open_columns],
        width="stretch",
        hide_index=True,
    )

with tab_records:
    visible_columns = [
        "Number",
        "Status",
        "Date Created",
        "Date Closed",
        "Closure Days",
        "Company",
        "Subject",
        "Assigned To",
        "Origin",
        "Type",
    ]
    visible_columns = [column for column in visible_columns if column in filtered.columns]
    st.dataframe(
        filtered.sort_values("Date Created", ascending=False)[visible_columns],
        width="stretch",
        hide_index=True,
    )
