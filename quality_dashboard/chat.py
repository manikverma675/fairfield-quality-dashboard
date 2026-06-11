from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI

from quality_dashboard.config import (
    DEFECT_FILE,
    EXTERNAL_FAILURE_FILE,
    NCR_CASES_FILE,
    SCRAP_FILE,
)

_SYSTEM_PROMPT = """\
You are a quality analytics assistant embedded in the Fairfield Processing Corporation (FPC) \
Quality Dashboard. Your only job is to answer questions about the quality data this dashboard tracks.

CURRENT DATA SNAPSHOT:
{context}

RULES — follow these exactly:
1. Only answer questions about the data above (NCR cases, customer complaints, weight inspection, \
scrap/quarantine, Amazon external failure claims).
2. If asked anything outside that scope (general knowledge, competitors, coding, personal topics, \
pricing not in the data, etc.) respond exactly: \
"I can only answer questions about the Fairfield quality dashboard data."
3. Always cite specific numbers from the data when answering. Never invent figures.
4. If the data doesn't contain enough information to answer, say so clearly and suggest which \
filter or page would show the relevant detail.
5. Keep answers concise (2–5 sentences) unless the user explicitly asks for detail.
6. Be direct and actionable — the audience is quality/operations managers, not data analysts.
"""


def _build_context() -> str:
    sections: list[str] = []

    # NCR & Complaints
    try:
        from quality_dashboard.data_loaders import load_ncr_cases
        from quality_dashboard.calculations import filter_ncr_profile, ncr_summary, ncr_company_summary

        cases = load_ncr_cases(NCR_CASES_FILE)
        ncr = filter_ncr_profile(cases, "FPC | NCR")
        complaints = filter_ncr_profile(cases, "FPC | Customer Support")
        ns = ncr_summary(ncr)
        cs = ncr_summary(complaints)

        top_co = ncr_company_summary(ncr, limit=5)
        top_str = ", ".join(
            f"{r['Company']} ({r['Cases']} cases, {r['Open Cases']} open)"
            for _, r in top_co.iterrows()
        )
        sections.append(
            f"NCR CASES: {ns['total']} total | {ns['open']} open | {ns['closed']} closed | "
            f"Median closure {ns['median_closure_days']:.1f} days | Avg open age {ns['avg_age_days']:.1f} days\n"
            f"Top companies by NCR count: {top_str}"
        )
        sections.append(
            f"CUSTOMER COMPLAINTS: {cs['total']} total | {cs['open']} open | {cs['closed']} closed | "
            f"Median closure {cs['median_closure_days']:.1f} days"
        )
    except Exception as exc:
        sections.append(f"NCR / COMPLAINTS: data unavailable ({exc})")

    # Scrap
    try:
        from quality_dashboard.data_loaders import load_scrap_data
        from quality_dashboard.calculations import scrap_summary

        scrap = load_scrap_data(SCRAP_FILE)
        ss = scrap_summary(scrap, "Confirmed Scrap")
        top_scrap = (
            scrap.groupby("Item")["Confirmed Scrap"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )
        top_str = ", ".join(f"{i} ({v:,.0f} units)" for i, v in top_scrap.items())
        sections.append(
            f"SCRAP / QUARANTINE: {ss['confirmed_scrap']:,.0f} units confirmed scrap | "
            f"{ss['into_quarantine']:,.0f} units into quarantine | "
            f"{ss['quarantine_balance']:,.0f} units quarantine balance | "
            f"{ss['transactions']:,} transactions across {ss['items']:,} items\n"
            f"Top scrap items: {top_str}"
        )
    except Exception as exc:
        sections.append(f"SCRAP: data unavailable ({exc})")

    # Weight inspection
    try:
        from quality_dashboard.data_loaders import load_defect_data
        from quality_dashboard.calculations import weight_summary, weight_item_summary

        meas = load_defect_data(DEFECT_FILE)
        ws = weight_summary(meas)
        top_items = weight_item_summary(meas, limit=5)
        top_str = ", ".join(
            f"{r['Assembly Item']} (avg abs variance {r['Average Absolute Variance']:.3f})"
            for _, r in top_items.iterrows()
        )
        sections.append(
            f"WEIGHT INSPECTION: {ws['measurements']:,} measurements | "
            f"{ws['comparable_measurements']:,} with expected weight | "
            f"Avg variance {ws['average_variance']:.3f} | Avg abs variance {ws['average_absolute_variance']:.3f} | "
            f"Max abs variance {ws['maximum_absolute_variance']:.3f}\n"
            f"Within range: {ws['within_range']:,} | Below expected: {ws['below_expected']:,} | "
            f"Above expected: {ws['above_expected']:,}\n"
            f"Top items by variance: {top_str}"
        )
    except Exception as exc:
        sections.append(f"WEIGHT INSPECTION: data unavailable ({exc})")

    # External failure
    try:
        from quality_dashboard.data_loaders import load_external_failure_data
        from quality_dashboard.calculations import external_failure_summary

        ext = load_external_failure_data(EXTERNAL_FAILURE_FILE)
        es = external_failure_summary(ext.top_claims, ext.defective_damaged)
        dept_total = ext.department_summary["Claim Amount"].sum()

        top_reasons = (
            ext.top_claims.groupby("Claim Reason")["Claim Amount"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )
        reasons_str = ", ".join(f"{r} (${v:,.0f})" for r, v in top_reasons.items())

        top_items = (
            ext.top_claims.groupby("Item Description")["Claim Amount"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )
        items_str = ", ".join(f"{i} (${v:,.0f})" for i, v in top_items.items())

        sections.append(
            f"EXTERNAL FAILURE (AMAZON CLAIMS): dept total ${dept_total:,.2f} | "
            f"line-item total ${es['total_claims']:,.2f} | {es['claim_rows']:,} claim lines | "
            f"Defect/Damage cost ${es['defect_damage_cost']:,.2f} ({es['defect_damage_units']:,.0f} units)\n"
            f"Top claim reasons: {reasons_str}\n"
            f"Top claimed items: {items_str}"
        )
    except Exception as exc:
        sections.append(f"EXTERNAL FAILURE: data unavailable ({exc})")

    return "\n\n".join(sections)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_context() -> str:
    return _build_context()


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=st.secrets["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )


def _stream_chunks(stream):
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


@st.dialog("Ask about your quality data", width="large")
def _chat_dialog() -> None:
    context = _cached_context()
    system_prompt = _SYSTEM_PROMPT.format(context=context)

    if "fpc_chat_history" not in st.session_state:
        st.session_state.fpc_chat_history = []

    # Render history
    for msg in st.session_state.fpc_chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about NCR cases, scrap, weight inspection, claims…"):
        st.session_state.fpc_chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        api_messages = [{"role": "system", "content": system_prompt}] + [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.fpc_chat_history
        ]

        try:
            client = _get_client()
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=api_messages,
                stream=True,
                max_tokens=600,
                temperature=0.2,
            )
            with st.chat_message("assistant"):
                response_text = st.write_stream(_stream_chunks(stream))
            st.session_state.fpc_chat_history.append(
                {"role": "assistant", "content": response_text}
            )
        except Exception as exc:
            st.error(f"Could not reach DeepSeek: {exc}")

    if st.session_state.fpc_chat_history:
        if st.button("Clear conversation", type="secondary"):
            st.session_state.fpc_chat_history = []
            st.rerun()


_FLOAT_JS = """
<script>
(function () {
    function applyFloat() {
        try {
            const doc = window.parent.document;
            const btns = doc.querySelectorAll('button');
            for (const btn of btns) {
                const txt = btn.innerText || btn.textContent || '';
                if (txt.trim() === '💬') {
                    const wrap = btn.closest('[data-testid="stButton"]') || btn.parentElement;
                    Object.assign(wrap.style, {
                        position: 'fixed',
                        bottom: '2rem',
                        right: '2rem',
                        zIndex: '99999',
                        margin: '0',
                    });
                    Object.assign(btn.style, {
                        width: '3.5rem',
                        height: '3.5rem',
                        borderRadius: '50%',
                        backgroundColor: '#d97706',
                        color: 'white',
                        fontSize: '1.5rem',
                        border: 'none',
                        boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
                        padding: '0',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        lineHeight: '1',
                    });
                    btn.title = 'Ask AI about your quality data';
                    btn.onmouseenter = () => {
                        btn.style.backgroundColor = '#b45309';
                        btn.style.transform = 'scale(1.08)';
                        btn.style.transition = 'all 0.15s';
                    };
                    btn.onmouseleave = () => {
                        btn.style.backgroundColor = '#d97706';
                        btn.style.transform = 'scale(1)';
                    };
                    break;
                }
            }
        } catch (e) { /* cross-origin or not ready */ }
    }

    // Run immediately and after short delay (Streamlit renders async)
    applyFloat();
    setTimeout(applyFloat, 400);
    setTimeout(applyFloat, 1200);

    // Re-apply whenever Streamlit rerenders the DOM
    try {
        const observer = new MutationObserver(() => setTimeout(applyFloat, 100));
        observer.observe(window.parent.document.body, { childList: true, subtree: true });
    } catch (e) {}
})();
</script>
"""


def render_chat_widget() -> None:
    """Inject the floating chat button + dialog. Call once from App.py after pg.run()."""
    # JavaScript to float the button (runs in same-origin iframe)
    components.html(_FLOAT_JS, height=0)

    # The actual Streamlit button — JS above moves it to fixed bottom-right
    if st.button("💬", key="fpc_chat_fab"):
        _chat_dialog()
