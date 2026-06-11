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
You are a quality analytics assistant embedded in the Fairfield Processing Corporation (FPC) \
Quality Dashboard. Your only job is to answer questions about the quality data this dashboard tracks.

CURRENT DATA SNAPSHOT:
{context}

RULES — follow these exactly:
1. Only answer questions about the data above (NCR cases, customer complaints, weight inspection, \
scrap/quarantine, Amazon external failure claims).
2. If asked anything outside that scope respond exactly: \
"I can only answer questions about the Fairfield quality dashboard data."
3. Always cite specific numbers from the data when answering. Never invent figures.
4. If the data does not contain enough information to answer, say so clearly.
5. Keep answers concise (2–5 sentences) unless the user explicitly asks for detail.
6. Be direct and actionable — the audience is quality/operations managers.
"""


def _build_context() -> str:
    sections: list[str] = []

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
            f"SCRAP / QUARANTINE: {ss['confirmed_scrap']:,.0f} confirmed scrap units | "
            f"{ss['into_quarantine']:,.0f} into quarantine | "
            f"{ss['quarantine_balance']:,.0f} quarantine balance | "
            f"{ss['transactions']:,} transactions across {ss['items']:,} items\n"
            f"Top scrap items: {top_str}"
        )
    except Exception as exc:
        sections.append(f"SCRAP: data unavailable ({exc})")

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
            f"Defect/Damage ${es['defect_damage_cost']:,.2f} ({es['defect_damage_units']:,.0f} units)\n"
            f"Top claim reasons: {reasons_str}\n"
            f"Top claimed items: {items_str}"
        )
    except Exception as exc:
        sections.append(f"EXTERNAL FAILURE: data unavailable ({exc})")

    return "\n\n".join(sections)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_context() -> str:
    return _build_context()


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
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: transparent;
    overflow: hidden;
}}

/* FAB */
#fab {{
    position: fixed;
    bottom: 1rem;
    right: 1rem;
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
    position: fixed;
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
                <p>Powered by DeepSeek</p>
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

function setFrameSize(open) {{
    const f = window.frameElement;
    if (!f) return;
    f.style.border = 'none';
    f.style.zIndex = '99999';
    f.style.position = 'fixed';
    if (open) {{
        f.style.bottom = '0';
        f.style.right = '2rem';
        f.style.width = '380px';
        f.style.height = '520px';
        f.style.borderRadius = '16px 16px 0 0';
        f.style.boxShadow = '0 -6px 40px rgba(0,0,0,0.16)';
    }} else {{
        f.style.bottom = '1.5rem';
        f.style.right = '1.5rem';
        f.style.width = '62px';
        f.style.height = '62px';
        f.style.borderRadius = '50%';
        f.style.boxShadow = '0 4px 16px rgba(0,0,0,0.25)';
    }}
}}

function openChat() {{
    document.getElementById('fab').style.display = 'none';
    document.getElementById('card').classList.add('open');
    setFrameSize(true);
    document.getElementById('user-input').focus();
}}

function closeChat() {{
    document.getElementById('card').classList.remove('open');
    document.getElementById('fab').style.display = 'flex';
    setFrameSize(false);
}}

window.addEventListener('load', () => setFrameSize(false));

function scrollBottom() {{
    const m = document.getElementById('messages');
    m.scrollTop = m.scrollHeight;
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
    bubble.textContent = text;
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
                        bubble.textContent = full;
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

    components.html(html, height=70)
