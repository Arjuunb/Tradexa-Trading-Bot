"""Safety Center — the progression flow, data separation and a kill switch."""
from __future__ import annotations

import streamlit as st

from trading_bot.safety import gates
from trading_bot.ui.components import get_api, offline


def render():
    st.header("Safety Center")
    api = get_api()
    sysd = api.system_status()
    if offline(sysd):
        return

    st.subheader("Required Progression")
    st.write(" → ".join(gates.PROGRESSION))
    st.caption("New strategies can never skip steps. Live stays locked until every "
               "earlier stage has real, recorded results.")

    has_backtest = bool(st.session_state.get("bt_result"))
    has_sim = bool(st.session_state.get("sim_runs"))
    has_paper = len(api.trades()) > 0
    stages = [
        ("Backtest", has_backtest),
        ("Simulation", has_sim),
        ("Paper Trading", has_paper),
        ("Live Trading", bool(sysd.get("broker_connected"))),
    ]
    for name, done in stages:
        st.write(f"{'✅' if done else '⬜'} {name}")

    st.divider()
    st.subheader("Data Separation")
    st.write("Each dataset is kept strictly separate and never cross-shown:")
    st.write("- **Backtest** — historical, on Backtesting page")
    st.write("- **Simulation** — forward sim, on Simulation page")
    st.write("- **Paper** — real engine, simulated money, on Paper Trading page")
    st.write("- **Live** — locked; no live data exists until a broker is connected")

    st.divider()
    st.subheader("Emergency Controls")
    st.warning("Kill switch halts all trading immediately (paper engine).")
    if st.button("🛑 KILL SWITCH — Stop Everything", type="primary", use_container_width=True):
        api.stop()
        api.engine_stop()
        st.toast("All trading halted")
