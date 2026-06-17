"""Simulation — forward-style run of a custom strategy spec on historical bars.

This is step 2 of the safety flow (Backtest -> Simulation -> Paper -> Live).
Results are stored in session as the strategy's simulation evidence.
"""
from __future__ import annotations

import streamlit as st

from trading_bot.models.schemas import StrategySpec
from trading_bot.ui.components import get_api, offline


def render():
    st.header("Simulation")
    st.caption("Simulated data only — distinct from backtest, paper and live datasets.")
    api = get_api()
    if offline(api.system_status()):
        return

    customs = api.custom_list()
    if not customs:
        st.info("No custom strategies to simulate. Build one on the Strategies page.")
        return

    names = {c.get("name", c.get("id")): c for c in customs}
    choice = st.selectbox("Strategy", list(names))
    bars = st.number_input("Bars", 500, 10000, 3000, 500)
    spec = names[choice]

    if st.button("▶ Run Simulation", use_container_width=True):
        with st.spinner("Simulating…"):
            res = api.simulate(spec, bars=int(bars))
        if "error" in res:
            st.error(res["error"])
        else:
            sims = st.session_state.setdefault("sim_runs", {})
            sims[spec.get("id") or choice] = res
            st.success("Simulation complete and recorded for the safety flow.")

    sims = st.session_state.get("sim_runs", {})
    res = sims.get(spec.get("id") or choice)
    if res:
        m = res.get("metrics", res)
        k = st.columns(4)
        k[0].metric("Trades", m.get("trades", 0))
        k[1].metric("Win Rate", f"{m.get('win_rate', 0):.1f}%")
        k[2].metric("Profit Factor", f"{m.get('profit_factor', 0):.2f}")
        k[3].metric("Net P&L", f"${m.get('net_pnl', 0):,.0f}")
        st.json(m, expanded=False)
