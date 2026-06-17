"""Markets — watchlist of the symbols the engine is actually trading."""
from __future__ import annotations

import streamlit as st

from trading_bot.ui.components import get_api, offline


def render():
    st.header("Markets")
    api = get_api()
    sysd = api.system_status()
    if offline(sysd):
        return

    cfg = api.settings() or {}
    symbols = cfg.get("symbols") or sysd.get("symbols") or []
    positions = {p.get("symbol"): p for p in api.positions()}

    c1, c2 = st.columns([3, 1])
    with c2:
        market = st.selectbox("Market type", ["All", "Crypto", "Equity", "Forex"])
        tf = st.selectbox("Timeframe", ["All", "1h", "4h", "1d"], index=0)
        st.caption(f"Filter: {market} / {tf}")

    with c1:
        st.subheader("Watchlist")
        if not symbols:
            st.info("No symbols configured. Add them on the Settings page.")
        else:
            rows = []
            for sym in symbols:
                pos = positions.get(sym)
                rows.append({
                    "Symbol": sym,
                    "In Position": "Yes" if pos else "No",
                    "Size": pos.get("size") if pos else "—",
                    "Entry": pos.get("entry") if pos else "—",
                    # No live-quote feed in the backend — don't fabricate prices.
                    "Last": "—",
                    "Volatility": "—",
                    "Spread": "—",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.caption("Live quote / volatility / spread require a market-data feed "
                       "(not connected). Position columns are real engine state.")

    st.subheader("Market Status")
    st.write(f"**Engine:** {'Running' if sysd.get('engine_running') else 'Stopped'} · "
             f"**Mode:** {sysd.get('mode', 'paper').upper()} · "
             f"**Tracked symbols:** {len(symbols)}")
