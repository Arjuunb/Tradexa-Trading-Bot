"""Live Trading — LOCKED until the full safety flow passes and a broker connects.

New strategies can NEVER go straight to live. Required flow:
Backtest -> Simulation -> Paper Trading -> Live Trading.
"""
from __future__ import annotations

import streamlit as st

from trading_bot.safety import gates
from trading_bot.ui.components import get_api, offline


def render():
    st.header("Live Trading")
    api = get_api()
    sysd = api.system_status()
    if offline(sysd):
        return

    cfg = api.settings() or {}
    risk_cfg = cfg.get("risk") or api.risk() or {}
    broker_connected = bool(sysd.get("broker_connected"))

    # Evidence collected from this session's safety flow.
    has_backtest = bool(st.session_state.get("bt_result"))
    has_sim = bool(st.session_state.get("sim_runs"))
    trades = api.trades()
    has_paper = len(trades) > 0
    risk_ok = gates.risk_valid({
        "risk_per_trade_pct": risk_cfg.get("risk_per_trade_pct", 0),
        "max_drawdown_pct": risk_cfg.get("max_drawdown_pct", risk_cfg.get("max_daily_drawdown_pct", 0)),
        "max_open_positions": risk_cfg.get("max_open_positions", risk_cfg.get("max_concurrent", 0)),
    })

    user_confirmed = st.checkbox("I manually confirm I want to enable live trading.")

    items, all_passed = gates.live_checklist(
        has_backtest=has_backtest, has_simulation=has_sim, has_paper=has_paper,
        risk_ok=risk_ok, broker_connected=broker_connected, user_confirmed=user_confirmed,
    )

    st.subheader("Pre-flight Checklist")
    for label, ok in items:
        st.write(f"{'✅' if ok else '⛔'} {label}")

    st.divider()
    if not broker_connected:
        st.warning("No broker / exchange is connected. Live trading is **hardware-locked** "
                   "until a real broker integration is configured. This is intentional.")
    if all_passed:
        st.success("All gates passed. Live trading could be enabled once a broker is wired in.")
        st.button("🚀 Enable Live Trading", disabled=not broker_connected,
                  help="Disabled until a real broker connection exists.")
    else:
        st.error("Live trading is LOCKED — complete every checklist item above first.")
