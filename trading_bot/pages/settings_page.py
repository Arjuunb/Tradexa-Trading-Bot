"""Settings — symbols, risk, strategy params and Telegram alerts.

Reads/writes the backend's runtime settings (real persistence) plus a couple
of UI-only preferences stored locally.
"""
from __future__ import annotations

import streamlit as st

from trading_bot import database as db
from trading_bot.ui.components import get_api, offline


def render():
    st.header("Settings")
    api = get_api()
    if offline(api.system_status()):
        return

    cfg = api.settings() or {}
    tab_mkt, tab_strat, tab_alerts, tab_ui = st.tabs(
        ["Market", "Strategy & Risk", "Telegram Alerts", "Appearance"])

    with tab_mkt:
        st.subheader("Tracked Symbols")
        current = ", ".join(cfg.get("symbols", []))
        raw = st.text_area("Symbols (comma-separated)", current, height=80)
        if st.button("Save Symbols"):
            syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
            res = api.set_symbols(syms)
            st.toast("Saved" if "error" not in res else res["error"])

    with tab_strat:
        st.subheader("Strategy & Risk")
        strat = cfg.get("strategy", {})
        active = st.text_input("Active strategy", strat.get("active", "ensemble")
                               if isinstance(strat, dict) else str(strat))
        risk = cfg.get("risk", {})
        rpt = st.number_input("Risk per trade %", 0.1, 5.0,
                              float(risk.get("risk_per_trade_pct", 0.01)) * 100, 0.1) / 100.0
        mtd = st.number_input("Max trades / day", 0, 50, int(risk.get("max_trades_per_day", 0)))
        if st.button("Save Strategy & Risk"):
            res = api.update_settings({"strategy": {"active": active},
                                       "risk": {"risk_per_trade_pct": rpt, "max_trades_per_day": mtd}})
            st.toast("Saved" if "error" not in res else res["error"])

    with tab_alerts:
        st.subheader("Telegram Notifications")
        notif = api.notif_status() or {}
        st.write(f"Status: {'🟢 Configured' if notif.get('configured') else '⚪ Not configured'}")
        enabled = st.checkbox("Enable Telegram alerts", value=bool(notif.get("enabled")))
        token = st.text_input("Bot token", type="password",
                              placeholder="leave blank to keep existing")
        chat_id = st.text_input("Chat ID", value=str(notif.get("chat_id", "")))
        c1, c2 = st.columns(2)
        if c1.button("Save Alerts"):
            body = {"enabled": enabled, "chat_id": chat_id}
            if token:
                body["token"] = token
            res = api.notif_update(body)
            st.toast("Saved" if "error" not in res else res["error"])
        if c2.button("Send Test Message"):
            res = api.notif_test()
            st.toast("Sent" if "error" not in res else res["error"])

    with tab_ui:
        st.subheader("Appearance (local UI preference)")
        theme = st.selectbox("Theme", ["dark", "light"],
                             index=0 if db.get_pref("theme", "dark") == "dark" else 1)
        if st.button("Save Appearance"):
            db.set_pref("theme", theme)
            st.toast("Saved locally")
