"""Strategies — list built-in + custom strategies and a rule-based builder.

The builder posts a StrategySpec to the backend, which validates it, can
simulate it, and (only after the safety flow) deploy it to paper trading.
"""
from __future__ import annotations

import streamlit as st

from trading_bot.models.schemas import StrategySpec
from trading_bot.ui.components import get_api, offline


def render():
    st.header("Strategies")
    api = get_api()
    sysd = api.system_status()
    if offline(sysd):
        return

    tab_lib, tab_build = st.tabs(["Library", "Strategy Builder"])

    with tab_lib:
        st.subheader("Built-in")
        lib = api.strategy_list() or {}
        builtins = lib.get("builtin") or lib.get("strategies") or []
        if builtins:
            for s in builtins:
                name = s if isinstance(s, str) else s.get("name", "?")
                st.write(f"• **{name}**")
        else:
            st.caption("No built-in strategies reported.")

        st.subheader("Custom")
        customs = api.custom_list()
        if not customs:
            st.caption("No custom strategies yet. Build one in the next tab.")
        for cs in customs:
            sid = cs.get("id")
            with st.container(border=True):
                st.write(f"**{cs.get('name', 'Unnamed')}** · {cs.get('symbol')} {cs.get('timeframe')} "
                         f"· {cs.get('side', 'long')}")
                b1, b2, b3 = st.columns(3)
                if b1.button("Duplicate", key=f"dup_{sid}"):
                    api.duplicate_strategy(sid); st.toast("Duplicated"); st.rerun()
                if b2.button("Deploy → Paper", key=f"dep_{sid}"):
                    res = api.deploy_strategy(sid)
                    st.toast("Deployed to paper" if "error" not in res else res["error"])
                if b3.button("Delete", key=f"del_{sid}"):
                    api.delete_strategy(sid); st.toast("Deleted"); st.rerun()

    with tab_build:
        _builder(api)


def _builder(api):
    st.subheader("Rule-based Strategy Builder")
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Name", "My Strategy")
    symbol = c2.text_input("Symbol", "BTCUSDT")
    timeframe = c3.selectbox("Timeframe", ["1h", "4h", "1d"], index=1)
    side = c1.selectbox("Side", ["long", "short"])
    risk = c2.number_input("Risk per trade %", 0.1, 5.0, 1.0, 0.1) / 100.0
    max_td = c3.number_input("Max trades / day (0 = unlimited)", 0, 50, 0)

    st.markdown("**Entry rules** (combined with AND)")
    n = st.number_input("Number of rules", 1, 6, 2)
    rules = []
    rule_types = ["ema_cross", "rsi", "breakout_donchian", "supertrend", "price_above_ema"]
    for i in range(int(n)):
        rc1, rc2 = st.columns([1, 2])
        rtype = rc1.selectbox(f"Rule {i+1} type", rule_types, key=f"rt_{i}")
        param = rc2.text_input(f"Rule {i+1} params (e.g. period=20)", "period=20", key=f"rp_{i}")
        rule = {"type": rtype}
        for kv in param.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    rule[k.strip()] = float(v) if "." in v else int(v)
                except ValueError:
                    rule[k.strip()] = v.strip()
        rules.append(rule)

    spec = StrategySpec(
        name=name, symbol=symbol, timeframe=timeframe, side=side,
        risk_per_trade_pct=risk, max_trades_per_day=int(max_td),
    ).model_dump()
    spec["entry"] = {"op": "AND", "rules": rules}

    b1, b2 = st.columns(2)
    if b1.button("▶ Simulate", use_container_width=True):
        with st.spinner("Simulating on historical data…"):
            res = api.simulate(spec, bars=3000)
        if "error" in res:
            st.error(res["error"])
        else:
            st.session_state["sim_result"] = res
    if b2.button("💾 Save Strategy", use_container_width=True):
        res = api.save_strategy(spec)
        st.toast("Saved" if "error" not in res else res["error"])

    res = st.session_state.get("sim_result")
    if res:
        st.subheader("Simulation Result")
        m = res.get("metrics", res)
        k = st.columns(4)
        k[0].metric("Trades", m.get("trades", 0))
        k[1].metric("Win Rate", f"{m.get('win_rate', 0):.1f}%")
        k[2].metric("Profit Factor", f"{m.get('profit_factor', 0):.2f}")
        k[3].metric("Net P&L", f"${m.get('net_pnl', 0):,.0f}")
        st.caption("Simulation only — not live performance. Saving makes it available "
                   "to deploy through the safety flow.")
