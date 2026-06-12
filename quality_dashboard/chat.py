"""Streamlit UI for the agentic quality assistant.

The heavy lifting (loading data, the SQL tool, the LLM tool-calling loop) lives in
quality_dashboard.assistant. This module is just the chat surface: a floating
chat-bubble widget (FAB button + popup card) rendered server-side, so it can run
the agent's data queries while keeping the familiar bubble UX.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from quality_dashboard.assistant import (
    build_frames,
    build_system_prompt,
    run_agent,
)


@st.cache_resource(show_spinner=False)
def _frames() -> dict[str, pd.DataFrame]:
    # Loaded once per server process; a hard refresh/redeploy rebuilds it.
    return build_frames()


@st.cache_resource(show_spinner=False)
def _system_prompt() -> str:
    return build_system_prompt(_frames())


_WIDGET_CSS = """
<style>
/* Floating launcher button (the 💬 / ✕ FAB) */
.st-key-fpc_fab button {
    position: fixed;
    bottom: 22px;
    right: 24px;
    width: 56px;
    height: 56px;
    min-height: 56px;
    border-radius: 50%;
    background: #d97706;
    color: #fff;
    font-size: 1.4rem;
    border: none;
    box-shadow: 0 4px 16px rgba(0,0,0,0.28);
    z-index: 1000001;
    transition: background 0.15s, transform 0.15s;
}
.st-key-fpc_fab button:hover {
    background: #b45309;
    transform: scale(1.07);
    color: #fff;
}

/* Floating chat card */
.st-key-fpc_card {
    position: fixed;
    bottom: 90px;
    right: 24px;
    width: 400px;
    max-width: calc(100vw - 48px);
    background: #fff;
    border: 1px solid #e7e5e4;
    border-radius: 16px;
    box-shadow: 0 8px 40px rgba(0,0,0,0.18);
    z-index: 1000000;
    padding: 0.6rem 0.9rem 0.9rem;
}
.st-key-fpc_card .fpc-title {
    font-weight: 600;
    color: #d97706;
    font-size: 0.98rem;
    padding: 0.1rem 0.2rem 0.4rem;
    border-bottom: 1px solid #f0eeec;
    margin-bottom: 0.3rem;
}

/* Scrollable message area inside the card — drop the default box border */
.st-key-fpc_msgs {
    border: none !important;
    padding: 0 !important;
    background: transparent !important;
}

/* Orange send button */
.st-key-fpc_card [data-testid="stFormSubmitButton"] button {
    background: #d97706;
    color: #fff;
    border: none;
    border-radius: 10px;
}
.st-key-fpc_card [data-testid="stFormSubmitButton"] button:hover {
    background: #b45309;
    color: #fff;
}
</style>
"""


def _process(prompt: str, api_key: str) -> None:
    messages = st.session_state["qa_messages"]
    messages.append({"role": "user", "content": prompt})
    history = [{"role": m["role"], "content": m["content"]} for m in messages]
    with st.spinner("Analyzing your quality data…"):
        answer, queries = run_agent(_frames(), _system_prompt(), api_key, history)
    messages.append({"role": "assistant", "content": answer, "queries": queries})


def render_chat_widget() -> None:
    """Floating chat-bubble assistant: a FAB that opens a popup card, powered by the agent."""
    api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
    st.session_state.setdefault("qa_messages", [])
    st.session_state.setdefault("qa_open", False)

    st.markdown(_WIDGET_CSS, unsafe_allow_html=True)

    # Launcher / close button — always present, pinned bottom-right.
    with st.container(key="fpc_fab"):
        if st.button("✕" if st.session_state["qa_open"] else "💬", key="fpc_fab_btn"):
            st.session_state["qa_open"] = not st.session_state["qa_open"]
            st.rerun()

    if not st.session_state["qa_open"]:
        return

    with st.container(key="fpc_card"):
        st.markdown('<div class="fpc-title">FPC Quality Assistant</div>', unsafe_allow_html=True)

        with st.container(key="fpc_msgs", height=340):
            if not st.session_state["qa_messages"]:
                st.caption(
                    "Ask anything about NCR cases, complaints, scrap, weight inspection, or "
                    "Amazon/Walmart claims — down to individual records."
                )
            for message in st.session_state["qa_messages"]:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
                    if message.get("queries"):
                        with st.expander("Data queries used"):
                            for query in message["queries"]:
                                st.code(query, language="sql")

        with st.form("fpc_chat_form", clear_on_submit=True, border=False):
            prompt = st.text_input(
                "Message",
                label_visibility="collapsed",
                placeholder="Ask about your quality data…",
            )
            sent = st.form_submit_button("Send", use_container_width=True)

        if sent and prompt.strip():
            _process(prompt.strip(), api_key)
            st.rerun()
