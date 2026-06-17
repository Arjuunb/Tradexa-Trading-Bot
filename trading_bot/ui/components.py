"""Shared Streamlit helpers (KPI cards, banners, the cached API client)."""
from __future__ import annotations

import streamlit as st

from trading_bot.services.api import HubAPI


@st.cache_resource
def get_api() -> HubAPI:
    return HubAPI()


def money(n) -> str:
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "—"
    return f"{'+' if n >= 0 else '-'}${abs(n):,.2f}"


def kpi_row(items: list):
    """items = [(label, value, optional_delta), ...]"""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value = item[0], item[1]
        delta = item[2] if len(item) > 2 else None
        col.metric(label, value, delta)


def offline(status) -> bool:
    """Render an offline banner if the backend is unreachable. Returns True if offline."""
    if status is None:
        from trading_bot.config import settings
        st.error(f"⚠️ Backend not reachable at `{settings.api_base}`. "
                 f"Start it: `cd automation-hub && uvicorn app:app` (or set BOT_API_BASE).")
        return True
    return False


def mode_badge():
    st.caption("All data here is **paper / simulation** — live trading is locked until a broker is connected.")


def hhmm(ts) -> str:
    if not ts:
        return "—"
    t = ts.split("T")[1] if "T" in str(ts) else str(ts)
    return t[:8]
