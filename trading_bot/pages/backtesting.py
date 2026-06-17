"""Backtesting — run a built-in strategy over historical bars and view results.

Uses the backend's /strategy/compare endpoint, which backtests on real CSV
history. Results here are clearly labelled BACKTEST data only.
"""
from __future__ import annotations

import streamlit as st

from trading_bot.charts import plots, transforms as tf
from trading_bot.ui.components import get_api, offline


def render():
    st.header("Backtesting")
    st.caption("Historical backtest data — never shown as live or paper performance.")
    api = get_api()
    if offline(api.system_status()):
        return

    c1, c2, c3, c4 = st.columns(4)
    symbol = c1.text_input("Symbol", "BTCUSDT")
    timeframe = c2.selectbox("Timeframe", ["1h", "4h", "1d"], index=1)
    strategy = c3.selectbox("Strategy", ["supertrend", "donchian", "ensemble", "ema"])
    bars = c4.number_input("Bars", 500, 10000, 3000, 500)

    if st.button("▶ Run Backtest", use_container_width=True):
        with st.spinner("Backtesting on historical data…"):
            res = api.compare(symbol, timeframe, strategy, int(bars))
        if not res or "error" in (res or {}):
            st.error((res or {}).get("error", "Backtest failed — is the backend reachable?"))
        else:
            st.session_state["bt_result"] = res

    res = st.session_state.get("bt_result")
    if not res:
        st.info("Configure and run a backtest to see results.")
        return

    m = res.get("metrics", res)
    k = st.columns(4)
    k[0].metric("Net P&L", f"${m.get('net_pnl', 0):,.0f}")
    k[1].metric("Win Rate", f"{m.get('win_rate', 0):.1f}%")
    k[2].metric("Profit Factor", f"{m.get('profit_factor', 0):.2f}")
    k[3].metric("Max Drawdown", f"{m.get('max_drawdown_pct', 0):.1f}%")

    curve = res.get("equity_curve") or res.get("equity")
    if curve:
        cc1, cc2 = st.columns(2)
        with cc1:
            st.subheader("Equity Curve")
            st.plotly_chart(plots.equity_curve(curve), use_container_width=True)
        with cc2:
            st.subheader("Drawdown")
            st.plotly_chart(plots.drawdown_chart(curve), use_container_width=True)

    trades = res.get("trades") or []
    if trades:
        w, loss, be = tf.win_loss_counts(trades)
        st.subheader("Win / Loss")
        st.plotly_chart(plots.win_loss_doughnut(w, loss, be), use_container_width=True)
