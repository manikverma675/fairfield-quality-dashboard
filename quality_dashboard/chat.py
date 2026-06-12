from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

from quality_dashboard.config import (
    DEFECT_FILE,
    EXTERNAL_FAILURE_FILE,
    NCR_CASES_FILE,
    SCRAP_FILE,
)

_SYSTEM_PROMPT = """\
You are the quality analytics assistant for the Fairfield Processing Corporation (FPC) Quality \
Dashboard. You help quality and operations managers understand the data below, which covers NCR \
cases, customer complaints, weight inspection, scrap/quarantine movement, and Amazon external \
failure claims.

DATA YOU CAN SEE (this is everything the dashboard currently shows, including monthly trends):
{context}

How to work:
- Reason over the data above and answer as helpfully as you can. It includes totals, breakdowns, \
rankings, and month-by-month trends — use them. Before saying you lack something, check the \
relevant section; the answer is often there (e.g. trend questions → the "MONTHLY TREND" lines).
- When you cite a figure, take it from the data — never invent or estimate numbers that aren't there.
- If a specific number genuinely isn't in the data, say what you do have and what's missing, and \
point the user to the page or filter that would show it. Don't refuse outright if you can partly help.
- Stay on the dashboard's subject matter. If someone asks something clearly unrelated (general \
knowledge, coding, other companies, personal topics), politely decline in your own words and steer \
them back to the quality data — no need for a canned phrase.
- Be direct and concise (usually 2–5 sentences); expand only when asked for detail. Lead with the \
answer, not a disclaimer.
- Write in clean, readable prose. Light **bold** for key numbers is fine; avoid headings, tables, \
and long bullet lists in such a small chat window.
"""


def _fmt_monthly(df, value_col: str, fmt: str = "{:.0f}", period_col: str = "Period") -> str:
    import pandas as pd

    parts = []
    for _, row in df.iterrows():
        period = pd.Timestamp(row[period_col]).strftime("%Y-%m")
        parts.append(f"{period}:{fmt.format(row[value_col])}")
    return ", ".join(parts)


def _build_context() -> str:
    sections: list[str] = []

    try:
        from quality_dashboard.data_loaders import load_ncr_cases
        from quality_dashboard.calculations import (
            filter_ncr_profile,
            filter_complaints,
            ncr_summary,
            ncr_company_summary,
            ncr_created_trend,
            ncr_closure_trend,
            ncr_status_summary,
            open_case_aging,
        )

        cases = load_ncr_cases(NCR_CASES_FILE)
        ncr = filter_ncr_profile(cases, "FPC | NCR")
        complaints = filter_complaints(cases)
        ns = ncr_summary(ncr)
        cs = ncr_summary(complaints)
        top_co = ncr_company_summary(ncr, limit=5)
        top_str = ", ".join(
            f"{r['Company']} ({r['Cases']} cases, {r['Open Cases']} open)"
            for _, r in top_co.iterrows()
        )
        ncr_status = ncr_status_summary(ncr)
        status_str = ", ".join(f"{r['Status']}: {r['Cases']}" for _, r in ncr_status.iterrows())
        ncr_aging = open_case_aging(ncr)
        aging_str = ", ".join(f"{r['Age Bucket']}d:{r['Cases']}" for _, r in ncr_aging.iterrows())

        ncr_created = ncr_created_trend(ncr, "Monthly")
        ncr_closure = ncr_closure_trend(ncr, "Monthly")
        created_str = _fmt_monthly(ncr_created, "Created Cases")
        closure_str = _fmt_monthly(ncr_closure, "Median Closure Days", "{:.0f}")

        sections.append(
            f"NCR CASES: {ns['total']} total | {ns['open']} open | {ns['closed']} closed | "
            f"Median closure {ns['median_closure_days']:.1f} days | Avg open age {ns['avg_age_days']:.1f} days\n"
            f"Status breakdown: {status_str}\n"
            f"Open backlog aging (days bucket:open cases): {aging_str}\n"
            f"Top companies by NCR count: {top_str}\n"
            f"MONTHLY TREND — NCRs created (YYYY-MM:count): {created_str}\n"
            f"MONTHLY TREND — median closure days (YYYY-MM:days): {closure_str}"
        )

        comp_status = ncr_status_summary(complaints)
        comp_status_str = ", ".join(f"{r['Status']}: {r['Cases']}" for _, r in comp_status.iterrows())
        comp_co = ncr_company_summary(complaints, limit=5)
        comp_co_str = ", ".join(
            f"{r['Company']} ({r['Cases']} cases, {r['Open Cases']} open)" for _, r in comp_co.iterrows()
        )
        comp_aging = open_case_aging(complaints)
        comp_aging_str = ", ".join(f"{r['Age Bucket']}d:{r['Cases']}" for _, r in comp_aging.iterrows())
        comp_created = ncr_created_trend(complaints, "Monthly")
        comp_closure = ncr_closure_trend(complaints, "Monthly")
        comp_str = _fmt_monthly(comp_created, "Created Cases")
        comp_closure_str = _fmt_monthly(comp_closure, "Median Closure Days", "{:.0f}")
        sections.append(
            f"CUSTOMER COMPLAINTS: {cs['total']} total | {cs['open']} open | {cs['closed']} closed | "
            f"Median closure {cs['median_closure_days']:.1f} days "
            f"(definition: FPC | NCR profile cases assigned to Sheri King; "
            f"complaint rate cannot be computed — no shipment/order denominator in the data)\n"
            f"Status breakdown: {comp_status_str}\n"
            f"Open backlog aging (days bucket:open cases): {comp_aging_str}\n"
            f"Top companies by complaint count: {comp_co_str}\n"
            f"MONTHLY TREND — open complaints created per month (YYYY-MM:count): {comp_str}\n"
            f"MONTHLY TREND — closed complaints created per month (YYYY-MM:count): {_fmt_monthly(comp_created, 'Closed Cases')}\n"
            f"MONTHLY TREND — median complaint closure days (YYYY-MM:days): {comp_closure_str}"
        )
    except Exception as exc:
        sections.append(f"NCR / COMPLAINTS: data unavailable ({exc})")

    try:
        from quality_dashboard.data_loaders import load_scrap_data
        from quality_dashboard.calculations import scrap_summary, scrap_rate_trend

        scrap = load_scrap_data(SCRAP_FILE)
        ss = scrap_summary(scrap, "Confirmed Scrap")
        top_scrap = (
            scrap.groupby("Item")["Confirmed Scrap"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
        )
        top_str = ", ".join(f"{i} ({v:,.0f} units)" for i, v in top_scrap.items())
        conf_rate = (
            ss["confirmed_scrap"] / ss["into_quarantine"] if ss["into_quarantine"] else float("nan")
        )
        scrap_monthly = scrap_rate_trend(scrap, "Monthly")
        confirmed_str = _fmt_monthly(scrap_monthly, "Confirmed Scrap")
        quar_str = _fmt_monthly(scrap_monthly, "Into Quarantine")
        sections.append(
            f"SCRAP / QUARANTINE: {ss['confirmed_scrap']:,.0f} confirmed scrap units | "
            f"{ss['into_quarantine']:,.0f} into quarantine | "
            f"{ss['quarantine_balance']:,.0f} quarantine balance | "
            f"Overall confirmation rate {conf_rate:.1%} (confirmed scrap / into quarantine) | "
            f"{ss['transactions']:,} transactions across {ss['items']:,} items\n"
            f"Top scrap items: {top_str}\n"
            f"MONTHLY TREND — confirmed scrap units (YYYY-MM:units): {confirmed_str}\n"
            f"MONTHLY TREND — into quarantine units (YYYY-MM:units): {quar_str}\n"
            f"Note: per-period confirmation rate can exceed 100% because items quarantined in "
            f"one month are often confirmed/disposed in a later month."
        )
    except Exception as exc:
        sections.append(f"SCRAP: data unavailable ({exc})")

    try:
        from quality_dashboard.data_loaders import load_defect_data
        from quality_dashboard.calculations import (
            weight_summary,
            weight_item_summary,
            weight_trend,
            weight_work_order_summary,
            weight_inspector_summary,
        )

        meas = load_defect_data(DEFECT_FILE)
        ws = weight_summary(meas)
        top_items = weight_item_summary(meas, limit=5)
        top_str = ", ".join(
            f"{r['Assembly Item']} (avg abs variance {r['Average Absolute Variance']:.3f})"
            for _, r in top_items.iterrows()
        )
        wo = weight_work_order_summary(meas, limit=5)
        wo_str = ", ".join(
            f"{r['Assembly Item']}|{r['Work Order']} (avg abs var {r['Average Absolute Variance']:.3f}, "
            f"{int(r['Measurements'])} meas)"
            for _, r in wo.iterrows()
        )
        insp = weight_inspector_summary(meas)
        insp_str = ", ".join(
            f"{r['Inspector']} (avg abs var {r['Average Absolute Variance']:.3f}, {int(r['Measurements'])} meas)"
            for _, r in insp.iterrows()
            if r["Inspector"]
        )
        wt_monthly = weight_trend(meas, "Monthly")
        wt_str = _fmt_monthly(wt_monthly, "Average Absolute Variance", "{:.3f}") if not wt_monthly.empty else "n/a"
        sections.append(
            f"WEIGHT INSPECTION: {ws['measurements']:,} measurements | "
            f"{ws['comparable_measurements']:,} with expected weight | "
            f"Avg variance {ws['average_variance']:.3f} | Avg abs variance {ws['average_absolute_variance']:.3f} | "
            f"Max abs variance {ws['maximum_absolute_variance']:.3f}\n"
            f"Within range: {ws['within_range']:,} | Below expected: {ws['below_expected']:,} | "
            f"Above expected: {ws['above_expected']:,}\n"
            f"Top items by variance: {top_str}\n"
            f"Worst work orders by variance: {wo_str}\n"
            f"Inspector performance (by avg abs variance): {insp_str}\n"
            f"MONTHLY TREND — avg absolute weight variance (YYYY-MM:variance): {wt_str}"
        )
    except Exception as exc:
        sections.append(f"WEIGHT INSPECTION: data unavailable ({exc})")

    try:
        from quality_dashboard.data_loaders import load_external_failure_data
        from quality_dashboard.calculations import external_failure_summary

        ext = load_external_failure_data(EXTERNAL_FAILURE_FILE)
        es = external_failure_summary(ext.top_claims)
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
        dept_rows = ext.department_summary.sort_values("Claim Amount", ascending=False)
        dept_str = ", ".join(
            f"{r['Department Description']} (${r['Claim Amount']:,.0f})" for _, r in dept_rows.iterrows()
        )
        sections.append(
            f"EXTERNAL FAILURE (AMAZON CLAIMS): dept total ${dept_total:,.2f} (authoritative, full reported total) | "
            f"line-item total ${es['total_claims']:,.2f} (detail sheet only) | {es['claim_rows']:,} claim lines | "
            f"{es['unique_items']:,} unique items | "
            f"defect/damage cost ${es['defect_damage_cost']:,.2f} | defect/damage lines {es['defect_damage_units']:,}\n"
            f"The ${dept_total - es['total_claims']:,.0f} gap between dept total and line-item total is claims "
            f"not itemized in the detail sheet.\n"
            f"Claim cost by department: {dept_str}\n"
            f"Top claim reasons: {reasons_str}\n"
            f"Top claimed items: {items_str}"
        )
    except Exception as exc:
        sections.append(f"EXTERNAL FAILURE: data unavailable ({exc})")

    return "\n\n".join(sections)


def _cached_context() -> str:
    # Build once per browser session and reuse on reruns. Using session_state
    # (not st.cache_data) means a hard refresh always rebuilds with the latest
    # code/data — no stale context lingering across deploys.
    if "fpc_chat_context" not in st.session_state:
        st.session_state["fpc_chat_context"] = _build_context()
    return st.session_state["fpc_chat_context"]


def render_chat_widget() -> None:
    """Floating chat card — no modal, no gray overlay, streams DeepSeek responses."""
    api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
    context = _cached_context()
    system_prompt = _SYSTEM_PROMPT.format(context=context)

    api_key_js = json.dumps(api_key)
    system_prompt_js = json.dumps(system_prompt)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
    width: 100%;
    height: 100%;
    position: relative;
}}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: transparent;
    overflow: hidden;
}}

/* FAB */
#fab {{
    position: absolute;
    bottom: 8px;
    right: 8px;
    width: 54px;
    height: 54px;
    border-radius: 50%;
    background: #d97706;
    color: white;
    font-size: 1.4rem;
    border: none;
    box-shadow: 0 4px 16px rgba(0,0,0,0.28);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, transform 0.15s;
    z-index: 10;
}}
#fab:hover {{ background: #b45309; transform: scale(1.08); }}

/* Chat card */
#card {{
    display: none;
    position: absolute;
    bottom: 0;
    right: 0;
    width: 100%;
    height: 100%;
    background: #fff;
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -6px 40px rgba(0,0,0,0.16);
    flex-direction: column;
    overflow: hidden;
}}
#card.open {{ display: flex; }}

/* Header */
#header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.9rem 1.1rem;
    background: #d97706;
    color: white;
    flex-shrink: 0;
}}
#header-left {{ display: flex; align-items: center; gap: 0.6rem; }}
#header-dot {{
    width: 9px; height: 9px;
    border-radius: 50%;
    background: #86efac;
    box-shadow: 0 0 0 2px rgba(255,255,255,0.4);
}}
#header h3 {{ font-size: 0.95rem; font-weight: 600; }}
#header p {{ font-size: 0.72rem; opacity: 0.85; margin-top: 1px; }}
#close-btn {{
    background: rgba(255,255,255,0.18);
    border: none;
    color: white;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    font-size: 1rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s;
}}
#close-btn:hover {{ background: rgba(255,255,255,0.32); }}

/* Messages */
#messages {{
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    background: #fafaf9;
    scroll-behavior: smooth;
}}
#messages::-webkit-scrollbar {{ width: 4px; }}
#messages::-webkit-scrollbar-track {{ background: transparent; }}
#messages::-webkit-scrollbar-thumb {{ background: #d6d3d1; border-radius: 4px; }}

.msg-row {{
    display: flex;
    flex-direction: column;
    max-width: 88%;
}}
.msg-row.user {{ align-self: flex-end; align-items: flex-end; }}
.msg-row.ai {{ align-self: flex-start; align-items: flex-start; }}

.bubble {{
    padding: 0.55rem 0.85rem;
    border-radius: 16px;
    font-size: 0.84rem;
    line-height: 1.55;
    word-break: break-word;
    white-space: pre-wrap;
}}
.user .bubble {{
    background: #d97706;
    color: white;
    border-bottom-right-radius: 4px;
}}
.ai .bubble {{
    background: white;
    color: #1c1917;
    border: 1px solid #e7e5e4;
    border-bottom-left-radius: 4px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}
.ai .bubble strong {{ font-weight: 700; color: #1c1917; }}
.ai .bubble code {{
    background: #f5f5f4;
    border: 1px solid #e7e5e4;
    border-radius: 4px;
    padding: 0 4px;
    font-size: 0.78rem;
    font-family: ui-monospace, monospace;
}}
.sender {{
    font-size: 0.68rem;
    color: #a8a29e;
    margin-bottom: 3px;
    padding: 0 3px;
}}

/* Typing dots */
.typing-bubble {{
    display: flex;
    gap: 5px;
    align-items: center;
    padding: 0.7rem 0.9rem;
    background: white;
    border: 1px solid #e7e5e4;
    border-radius: 16px;
    border-bottom-left-radius: 4px;
    width: fit-content;
}}
.dot {{
    width: 7px; height: 7px;
    background: #a8a29e;
    border-radius: 50%;
    animation: pulse 1.3s infinite ease-in-out;
}}
.dot:nth-child(2) {{ animation-delay: 0.2s; }}
.dot:nth-child(3) {{ animation-delay: 0.4s; }}
@keyframes pulse {{
    0%, 80%, 100% {{ transform: scale(0.7); opacity: 0.5; }}
    40% {{ transform: scale(1); opacity: 1; }}
}}

/* Input bar */
#input-bar {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.65rem 0.9rem;
    border-top: 1px solid #e7e5e4;
    background: white;
    flex-shrink: 0;
}}
#user-input {{
    flex: 1;
    border: 1.5px solid #e7e5e4;
    border-radius: 22px;
    padding: 0.5rem 1rem;
    font-size: 0.84rem;
    outline: none;
    font-family: inherit;
    color: #1c1917;
    background: #fafaf9;
    transition: border-color 0.15s;
}}
#user-input:focus {{ border-color: #d97706; }}
#user-input::placeholder {{ color: #a8a29e; }}
#send-btn {{
    width: 34px; height: 34px;
    border-radius: 50%;
    background: #d97706;
    color: white;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.85rem;
    flex-shrink: 0;
    transition: background 0.15s, transform 0.1s;
}}
#send-btn:hover {{ background: #b45309; transform: scale(1.06); }}
#send-btn:disabled {{ background: #d6d3d1; cursor: not-allowed; transform: none; }}
</style>
</head>
<body>

<button id="fab" onclick="openChat()" title="Ask AI about your quality data">💬</button>

<div id="card">
    <div id="header">
        <div id="header-left">
            <div id="header-dot"></div>
            <div>
                <h3>FPC Quality Assistant</h3>
                <p>Online</p>
            </div>
        </div>
        <button id="close-btn" onclick="closeChat()">✕</button>
    </div>
    <div id="messages">
        <div class="msg-row ai">
            <div class="sender">Assistant</div>
            <div class="bubble">Hi! Ask me anything about NCR cases, scrap, weight inspection, or Amazon claims.</div>
        </div>
    </div>
    <div id="input-bar">
        <input id="user-input" type="text" placeholder="Ask about your quality data…"
               onkeydown="if(event.key==='Enter')sendMessage()">
        <button id="send-btn" onclick="sendMessage()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
        </button>
    </div>
</div>

<script>
const API_KEY = {api_key_js};
const SYSTEM_PROMPT = {system_prompt_js};
const history = [];

function resizeFrame(h) {{
    // Primary: directly resize the srcdoc iframe (same-origin, always works)
    try {{
        const f = window.frameElement;
        if (f) {{
            f.style.height = h + 'px';
            f.style.maxHeight = h + 'px';
        }}
    }} catch(e) {{}}
    // Fallback: Streamlit's official resize protocol
    try {{
        window.parent.postMessage({{ type: 'streamlit:setFrameHeight', height: h }}, '*');
    }} catch(e) {{}}
}}

function openChat() {{
    document.getElementById('fab').style.display = 'none';
    document.getElementById('card').classList.add('open');
    resizeFrame(600);
    setTimeout(() => resizeFrame(600), 50);
    setTimeout(() => document.getElementById('user-input').focus(), 120);
}}

function closeChat() {{
    document.getElementById('card').classList.remove('open');
    document.getElementById('fab').style.display = 'flex';
    resizeFrame(80);
}}

function scrollBottom() {{
    const m = document.getElementById('messages');
    m.scrollTop = m.scrollHeight;
}}

function escapeHtml(s) {{
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}}

function mdToHtml(t) {{
    // Escape first so any tags in the text are neutralized, then apply light markdown.
    let h = escapeHtml(t);
    h = h.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');   // **bold**
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');                // `code`
    h = h.replace(/^[\\t ]*[-*] (.+)$/gm, '• $1');                  // - bullets
    h = h.replace(/^[\\t ]*#{{1,6}}\\s*(.+)$/gm, '<strong>$1</strong>'); // # headers
    h = h.replace(/\\n/g, '<br>');                                 // line breaks
    return h;
}}

function setContent(bubble, role, text) {{
    if (role === 'user') {{
        bubble.textContent = text;
    }} else {{
        bubble.innerHTML = mdToHtml(text);
    }}
}}

function addBubble(role, text) {{
    const msgs = document.getElementById('messages');
    const row = document.createElement('div');
    row.className = `msg-row ${{role === 'user' ? 'user' : 'ai'}}`;
    const sender = document.createElement('div');
    sender.className = 'sender';
    sender.textContent = role === 'user' ? 'You' : 'Assistant';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    setContent(bubble, role, text);
    row.appendChild(sender);
    row.appendChild(bubble);
    msgs.appendChild(row);
    scrollBottom();
    return bubble;
}}

function showTyping() {{
    const msgs = document.getElementById('messages');
    const row = document.createElement('div');
    row.className = 'msg-row ai';
    row.id = 'typing';
    const sender = document.createElement('div');
    sender.className = 'sender';
    sender.textContent = 'Assistant';
    const tb = document.createElement('div');
    tb.className = 'typing-bubble';
    tb.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
    row.appendChild(sender);
    row.appendChild(tb);
    msgs.appendChild(row);
    scrollBottom();
}}

function hideTyping() {{
    const el = document.getElementById('typing');
    if (el) el.remove();
}}

async function sendMessage() {{
    const input = document.getElementById('user-input');
    const btn = document.getElementById('send-btn');
    const text = input.value.trim();
    if (!text || btn.disabled) return;

    input.value = '';
    btn.disabled = true;

    addBubble('user', text);
    history.push({{ role: 'user', content: text }});
    showTyping();

    const messages = [
        {{ role: 'system', content: SYSTEM_PROMPT }},
        ...history
    ];

    try {{
        const res = await fetch('https://api.deepseek.com/chat/completions', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + API_KEY
            }},
            body: JSON.stringify({{
                model: 'deepseek-chat',
                messages,
                stream: true,
                max_tokens: 600,
                temperature: 0.2
            }})
        }});

        hideTyping();
        const bubble = addBubble('assistant', '');
        let full = '';

        const reader = res.body.getReader();
        const dec = new TextDecoder();

        while (true) {{
            const {{ done, value }} = await reader.read();
            if (done) break;
            const chunk = dec.decode(value, {{ stream: true }});
            for (const line of chunk.split('\\n')) {{
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6).trim();
                if (data === '[DONE]') continue;
                try {{
                    const token = JSON.parse(data)?.choices?.[0]?.delta?.content;
                    if (token) {{
                        full += token;
                        bubble.innerHTML = mdToHtml(full);
                        scrollBottom();
                    }}
                }} catch(e) {{}}
            }}
        }}

        history.push({{ role: 'assistant', content: full }});

    }} catch(err) {{
        hideTyping();
        addBubble('assistant', 'Could not reach the AI service. Please try again.');
    }}

    btn.disabled = false;
    input.focus();
}}
</script>
</body>
</html>"""

    # Pull the chat iframe out of normal page flow and pin it to the viewport.
    # This app has no other iframes (Altair charts render as inline SVG), so
    # targeting the iframe's container is safe.
    st.markdown(
        """
        <style>
        .stApp [data-testid="stElementContainer"]:has(> iframe),
        .stApp .element-container:has(> iframe) {
            position: fixed !important;
            bottom: 0 !important;
            right: 1.5rem !important;
            width: 420px !important;
            height: auto !important;
            margin: 0 !important;
            padding: 0 !important;
            z-index: 1000000 !important;
        }
        .stApp iframe[title="streamlit_app"],
        .stApp [data-testid="stElementContainer"]:has(> iframe) iframe,
        .stApp .element-container:has(> iframe) iframe {
            background: transparent !important;
            border: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(html, height=80)
