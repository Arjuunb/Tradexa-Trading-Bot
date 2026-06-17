"""Tradexa Bot Workspace — Streamlit entry point.

Run:  streamlit run trading_bot/app.py
Set:  BOT_API_BASE   (URL of the Automation Hub backend, default http://localhost:8000)
      BOT_WEBHOOK_SECRET (secret for write/control endpoints)

This UI is a thin, Python-only client over the existing backend. Every page
reads/writes real data through trading_bot/services/api.py — the same seam
Tradexa can integrate against later.
"""
from __future__ import annotations

import streamlit as st

from trading_bot.config import settings
from trading_bot.pages import (
    overview, markets, strategies, backtesting, simulation, paper_trading,
    live_trading, portfolio, analytics, ai_assistant, risk_manager, logs,
    settings_page, safety_center,
)

PAGES = {
    "📊 Overview": overview.render,
    "🌐 Markets": markets.render,
    "🧠 Strategies": strategies.render,
    "🧪 Backtesting": backtesting.render,
    "🔁 Simulation": simulation.render,
    "📝 Paper Trading": paper_trading.render,
    "🚀 Live Trading": live_trading.render,
    "💼 Portfolio": portfolio.render,
    "📈 Analytics": analytics.render,
    "🤖 AI Assistant": ai_assistant.render,
    "🛡 Risk Manager": risk_manager.render,
    "📜 Logs": logs.render,
    "⚙️ Settings": settings_page.render,
    "🔒 Safety Center": safety_center.render,
}


def main():
    st.set_page_config(page_title=settings.app_name, page_icon="🤖", layout="wide")
    st.sidebar.title("🤖 " + settings.app_name)
    st.sidebar.caption(f"Backend: `{settings.api_base}`")
    choice = st.sidebar.radio("Navigate", list(PAGES), label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption("Paper / simulation workspace. Live trading is locked.")
    PAGES[choice]()


if __name__ == "__main__":
    main()
