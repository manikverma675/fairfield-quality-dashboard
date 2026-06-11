import streamlit as st

from quality_dashboard.chat import render_chat_widget
from quality_dashboard.config import (
    DEFECT_FILE,
    EXTERNAL_FAILURE_FILE,
    NCR_CASES_FILE,
    SCRAP_FILE,
)
from quality_dashboard.ui import apply_theme


st.set_page_config(page_title="Fairfield Quality Dashboard", layout="wide")
apply_theme()


def home():
    st.title("Fairfield Quality Dashboard")
    st.caption("Separate quality views for NCRs, customer complaints, defects, scrap, and external failures.")

    pages = [
        ("NCR Cases", "pages/1_NCR_Cases.py", NCR_CASES_FILE),
        ("Customer Complaints", "pages/2_Customer_Complaints.py", NCR_CASES_FILE),
        ("Weight Inspection Analysis", "pages/3_Defect_Analysis.py", DEFECT_FILE),
        ("Scrap Analysis", "pages/4_Scrap_Analysis.py", SCRAP_FILE),
        ("External Failure Cost", "pages/5_External_Failure_Cost.py", EXTERNAL_FAILURE_FILE),
    ]

    for title, page_path, data_path in pages:
        left, right = st.columns([2, 3])
        with left:
            st.page_link(page_path, label=title)
        with right:
            status = "Ready" if data_path.exists() else "Missing"
            st.caption(f"{status}: {data_path.name}")


pg = st.navigation([
    st.Page(home, title="App", default=True),
    st.Page("pages/1_NCR_Cases.py", title="NCR Cases"),
    st.Page("pages/2_Customer_Complaints.py", title="Customer Complaints"),
    st.Page("pages/3_Defect_Analysis.py", title="Defect Analysis"),
    st.Page("pages/4_Scrap_Analysis.py", title="Scrap Analysis"),
    st.Page("pages/5_External_Failure_Cost.py", title="External Failure Cost"),
])
pg.run()
render_chat_widget()
