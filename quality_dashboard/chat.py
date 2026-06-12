"""Streamlit UI for the agentic quality assistant.

The heavy lifting (loading data, the SQL tool, the LLM tool-calling loop) lives in
quality_dashboard.assistant. This module is just the chat surface: it caches the
data tables and system prompt once per process, renders the conversation, and
routes each question through the agent.
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


def render_chat_widget() -> None:
    """Render the always-available 'Ask the Quality Assistant' chat at the bottom of the page."""
    api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
    messages = st.session_state.setdefault("qa_messages", [])

    with st.expander("💬 Ask the Quality Assistant", expanded=bool(messages)):
        if not messages:
            st.caption(
                "Ask anything about NCR cases, complaints, scrap, weight inspection, or "
                "Amazon/Walmart claims — down to individual records. I read the underlying "
                "tables directly to answer."
            )
        else:
            if st.button("Clear conversation", key="qa_clear"):
                st.session_state["qa_messages"] = []
                st.rerun()

        for message in messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message.get("queries"):
                    with st.expander("Data queries used"):
                        for query in message["queries"]:
                            st.code(query, language="sql")

    prompt = st.chat_input("Ask about your quality data…")
    if not prompt:
        return

    messages.append({"role": "user", "content": prompt})
    history = [{"role": m["role"], "content": m["content"]} for m in messages]

    with st.spinner("Analyzing your quality data…"):
        answer, queries = run_agent(_frames(), _system_prompt(), api_key, history)

    messages.append({"role": "assistant", "content": answer, "queries": queries})
    st.rerun()
