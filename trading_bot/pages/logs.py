"""Logs — the real event ledger and alert history, with CSV/JSON export."""
from __future__ import annotations

import streamlit as st

from trading_bot.ui.components import get_api, hhmm, offline


def render():
    st.header("Logs & Audit")
    api = get_api()
    if offline(api.system_status()):
        return

    tab_logs, tab_alerts = st.tabs(["Event Log", "Alerts"])

    with tab_logs:
        limit = st.slider("Rows", 50, 1000, 200, 50)
        logs = api.logs(limit)
        c1, c2 = st.columns(2)
        c1.link_button("⬇ Export CSV", api.export_url("logs", "csv"), use_container_width=True)
        c2.link_button("⬇ Export JSON", api.export_url("logs", "json"), use_container_width=True)
        if logs:
            st.dataframe(logs, use_container_width=True, hide_index=True)
        else:
            st.caption("No log entries.")

    with tab_alerts:
        alerts = api.alerts(200)
        st.link_button("⬇ Export Alerts CSV", api.export_url("alerts", "csv"))
        if alerts:
            for a in alerts:
                st.write(f"`{hhmm(a.get('ts'))}` **{a.get('title', '')}** — {a.get('detail', '')}")
        else:
            st.caption("No alerts.")
