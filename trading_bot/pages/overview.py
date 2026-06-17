"""Overview — bot status, account, today's P&L, open trades, risk, equity, alerts."""
from __future__ import annotations

import streamlit as st

from trading_bot.charts import plots
from trading_bot.ui.components import get_api, kpi_row, money, offline, hhmm


def render():
    st.header("Overview")
    api = get_api()
    sysd = api.system_status()
    if offline(sysd):
        return

    acct = api.account() or {}
    risk = api.risk() or {}
    perf = api.performance() or {}

    engine = "🟢 Running" if sysd.get("engine_running") else "🔴 Stopped"
    if sysd.get("auto_halted"):
        engine = "🟠 Auto-halted"
    kpi_row([
        ("Bot Status", engine),
        ("Mode", sysd.get("mode", "paper").upper()),
        ("Active Strategy", sysd.get("strategy", "—")),
        ("Balance", f"${(acct.get('balance') or 0):,.2f}"),
    ])
    kpi_row([
        ("Realized P&L", money(acct.get("realized_pnl"))),
        ("Open Trades", str(acct.get("open_positions", 0))),
        ("Exposure", f"{(risk.get('exposure_pct', 0) * 100):.1f}%"),
        ("Trading State", risk.get("trading_state", "—")),
    ])

    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("Equity Curve")
        st.plotly_chart(plots.equity_curve(api.equity_curve()), use_container_width=True)
    with c2:
        st.subheader("Quick Actions")
        if st.button("⏸ Pause All", use_container_width=True):
            api.pause(); st.toast("Paused")
        if st.button("■ Stop All", use_container_width=True):
            api.stop(); st.toast("Stopped")
        if st.button("▶ Resume", use_container_width=True):
            api.resume(); st.toast("Resumed")
        st.metric("Profit Factor", f"{perf.get('profit_factor', 0):.2f}")
        st.metric("Win Rate", f"{perf.get('win_rate', 0):.1f}%")

    st.subheader("Recent Alerts")
    alerts = api.alerts(8)
    if alerts:
        for a in alerts:
            st.write(f"`{hhmm(a.get('ts'))}` **{a.get('title')}** — {a.get('detail', '')}")
    else:
        st.caption("No alerts yet.")
