"""Paper Trading — the live (real-time, simulated-money) engine state.

All numbers here are REAL paper-engine state from the backend: account,
open positions and the closed-trade ledger. This is paper money, never live.
"""
from __future__ import annotations

import streamlit as st

from trading_bot.charts import plots, transforms as tf
from trading_bot.ui.components import get_api, kpi_row, money, offline


def render():
    st.header("Paper Trading")
    st.caption("Real engine state with simulated money. Not connected to any broker.")
    api = get_api()
    sysd = api.system_status()
    if offline(sysd):
        return

    acct = api.account() or {}
    kpi_row([
        ("Balance", f"${(acct.get('balance') or 0):,.2f}"),
        ("Equity", f"${(acct.get('equity') or acct.get('balance') or 0):,.2f}"),
        ("Realized P&L", money(acct.get("realized_pnl"))),
        ("Unrealized P&L", money(acct.get("unrealized_pnl"))),
    ])

    cc1, cc2 = st.columns([2, 1])
    with cc1:
        st.subheader("Engine Controls")
        b = st.columns(3)
        if b[0].button("▶ Start", use_container_width=True):
            api.engine_start(); st.toast("Engine started")
        if b[1].button("⏸ Pause", use_container_width=True):
            api.pause(); st.toast("Paused")
        if b[2].button("■ Stop", use_container_width=True):
            api.engine_stop(); st.toast("Engine stopped")
    with cc2:
        st.metric("Engine", "Running" if sysd.get("engine_running") else "Stopped")

    st.subheader("Open Positions")
    positions = api.positions()
    if positions:
        st.dataframe(positions, use_container_width=True, hide_index=True)
    else:
        st.caption("No open positions.")

    st.subheader("Closed Trades")
    trades = api.trades()
    if trades:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        days, pnls = tf.daily_pnl(trades)
        if days:
            st.subheader("Daily P&L")
            st.plotly_chart(plots.bar(days, pnls, name="pnl"), use_container_width=True)
    else:
        st.caption("No closed trades yet.")
