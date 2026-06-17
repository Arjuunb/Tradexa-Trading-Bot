"""AI Assistant — explains the bot's real state in plain English.

This is a deterministic, rule-based assistant over REAL backend data. It does
not invent numbers; if the backend has no data, it says so. (A future version
can swap in an LLM behind the same `answer()` seam.)
"""
from __future__ import annotations

import streamlit as st

from trading_bot.ui.components import get_api, offline


def _summary(api) -> dict:
    return {
        "status": api.system_status() or {},
        "account": api.account() or {},
        "perf": api.performance() or {},
        "risk": api.risk() or {},
        "positions": api.positions(),
    }


def answer(question: str, data: dict) -> str:
    q = question.lower()
    acct, perf, risk = data["account"], data["perf"], data["risk"]
    if any(w in q for w in ("balance", "account", "equity", "money")):
        return (f"Balance is ${acct.get('balance', 0):,.2f}, realized P&L "
                f"${acct.get('realized_pnl', 0):,.2f}, {len(data['positions'])} open positions.")
    if any(w in q for w in ("win", "performance", "profit", "how am i doing")):
        return (f"Win rate {perf.get('win_rate', 0):.1f}%, profit factor "
                f"{perf.get('profit_factor', 0):.2f} over {perf.get('trades', 0)} paper trades.")
    if any(w in q for w in ("risk", "exposure", "drawdown")):
        return (f"Exposure {risk.get('exposure_pct', 0) * 100:.1f}%, trading state "
                f"'{risk.get('trading_state', 'unknown')}'.")
    if any(w in q for w in ("live", "real money")):
        return ("Live trading is locked. The bot only trades paper money until the full "
                "safety flow passes and a broker is connected.")
    return ("I can answer about your balance, performance, risk/exposure and live-trading "
            "status — all from real backend data. Try asking one of those.")


def render():
    st.header("AI Assistant")
    st.caption("Answers come from real backend data — no fabricated numbers.")
    api = get_api()
    if offline(api.system_status()):
        return

    data = _summary(api)
    for sample in ("How is my account?", "How am I performing?", "What's my risk?"):
        if st.button(sample):
            st.session_state["ai_q"] = sample

    q = st.text_input("Ask about your bot", st.session_state.get("ai_q", ""))
    if q:
        st.info(answer(q, data))
