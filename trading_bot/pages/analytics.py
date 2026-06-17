"""Analytics — performance metrics and charts over real paper-trade history."""
from __future__ import annotations

import streamlit as st

from trading_bot.charts import plots, transforms as tf
from trading_bot.ui.components import get_api, kpi_row, offline


def render():
    st.header("Analytics")
    api = get_api()
    if offline(api.system_status()):
        return

    perf = api.performance() or {}
    trades = api.trades()
    curve = api.equity_curve()

    kpi_row([
        ("Total Trades", str(perf.get("trades", len(trades)))),
        ("Win Rate", f"{perf.get('win_rate', 0):.1f}%"),
        ("Profit Factor", f"{perf.get('profit_factor', 0):.2f}"),
        ("Max Drawdown", f"{perf.get('max_drawdown_pct', tf.max_drawdown_pct(tf.equity_values(curve))):.1f}%"),
    ])

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Equity Curve")
        st.plotly_chart(plots.equity_curve(curve), use_container_width=True)
        st.subheader("Drawdown")
        st.plotly_chart(plots.drawdown_chart(curve), use_container_width=True)
    with c2:
        st.subheader("Win / Loss")
        w, loss, be = tf.win_loss_counts(trades)
        st.plotly_chart(plots.win_loss_doughnut(w, loss, be), use_container_width=True)
        st.subheader("Daily P&L")
        days, pnls = tf.daily_pnl(trades)
        if days:
            st.plotly_chart(plots.bar(days, pnls, name="pnl"), use_container_width=True)
        else:
            st.caption("No closed trades yet.")

    st.subheader("Trade R-Multiple Distribution")
    labels, counts = tf.trade_r_distribution(trades)
    if labels:
        st.plotly_chart(plots.bar(labels, counts, color="#8b5cf6"), use_container_width=True)
    else:
        st.caption("No R-multiple data yet.")
