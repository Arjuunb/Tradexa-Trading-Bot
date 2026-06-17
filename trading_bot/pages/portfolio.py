"""Portfolio — allocation and exposure across open paper positions."""
from __future__ import annotations

import streamlit as st

from trading_bot.charts import plots, transforms as tf
from trading_bot.ui.components import get_api, kpi_row, money, offline


def render():
    st.header("Portfolio")
    api = get_api()
    if offline(api.system_status()):
        return

    acct = api.account() or {}
    positions = api.positions()
    risk = api.risk() or {}

    kpi_row([
        ("Equity", f"${(acct.get('equity') or acct.get('balance') or 0):,.2f}"),
        ("Open Positions", str(len(positions))),
        ("Exposure", f"{(risk.get('exposure_pct', 0) * 100):.1f}%"),
        ("Unrealized P&L", money(acct.get("unrealized_pnl"))),
    ])

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Allocation")
        labels, vals = tf.allocation_from_positions(positions)
        if labels:
            st.plotly_chart(plots.allocation_pie(labels, vals), use_container_width=True)
        else:
            st.caption("No open positions to allocate.")
    with c2:
        st.subheader("Positions")
        if positions:
            st.dataframe(positions, use_container_width=True, hide_index=True)
        else:
            st.caption("No open positions.")
