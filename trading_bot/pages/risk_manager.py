"""Risk Manager — view and edit risk limits; shows live risk state and guards."""
from __future__ import annotations

import streamlit as st

from trading_bot.charts import plots
from trading_bot.safety import gates
from trading_bot.ui.components import get_api, kpi_row, offline


def render():
    st.header("Risk Manager")
    api = get_api()
    if offline(api.system_status()):
        return

    risk = api.risk() or {}
    cfg = (api.settings() or {}).get("risk", {})

    kpi_row([
        ("Trading State", risk.get("trading_state", "—")),
        ("Exposure", f"{(risk.get('exposure_pct', 0) * 100):.1f}%"),
        ("Today P&L", f"${risk.get('today_pnl', 0):,.2f}"),
        ("Consec. Losses", str(risk.get("consecutive_losses", 0))),
    ])

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Exposure")
        st.plotly_chart(plots.gauge(risk.get("exposure_pct", 0) * 100, "Exposure %",
                                    maximum=100, threshold=80), use_container_width=True)
    with c2:
        st.subheader("Edit Risk Limits")
        rpt = st.number_input("Risk per trade %", 0.1, 5.0,
                              float(cfg.get("risk_per_trade_pct", 0.01)) * 100, 0.1) / 100.0
        mdd = st.number_input("Max drawdown %", 1.0, 90.0,
                              float(cfg.get("max_drawdown_pct", 20.0)), 1.0)
        mop = st.number_input("Max open positions", 1, 50,
                              int(cfg.get("max_open_positions", 5)))
        editable = {"risk_per_trade_pct": rpt, "max_drawdown_pct": mdd, "max_open_positions": mop}
        ok = gates.risk_valid(editable)
        st.write(f"{'✅ Valid' if ok else '⛔ Invalid'} risk configuration")
        if st.button("Save Risk Settings", disabled=not ok, use_container_width=True):
            res = api.update_settings({"risk": editable})
            st.toast("Saved" if "error" not in res else res["error"])

    st.subheader("Active Guards")
    guards = risk.get("guards") or risk.get("active_guards") or []
    if guards:
        for g in guards:
            st.write(f"• {g}")
    else:
        st.caption("No guards currently tripped.")
