"""Runtime-adjustable settings with cross-session persistence.

Only the values that are safe to change on a running bot live here (risk per
trade, exposure limit, max drawdown). They override the env defaults and are
persisted to a small JSON file so they survive a restart. Strategy / symbols /
timeframe require an engine restart and stay env-configured (read-only in the UI).
"""
from __future__ import annotations

import json
from pathlib import Path

EDITABLE = ("risk_per_trade_pct", "exposure_limit_pct", "max_drawdown_pct",
            "max_open_positions", "dedup_window_s", "max_daily_loss_pct",
            "session_start", "session_end", "max_weekly_loss_pct",
            "max_trades_per_day", "max_consecutive_losses", "cooldown_after_loss_min",
            "trading_days_mask", "notify_trades", "notify_risk",
            "engine_timeframe",
            # Runtime-settable AND restart-surviving. These were written by
            # _settings_snapshot but silently dropped on load until they joined
            # this list — the strategy choice and quality gate reverted on
            # every reboot.
            "auto_strategy", "entry_mode", "daily_report_hour",
            "min_quality_score", "streak_risk_scaling", "engine_symbols",
            "trading_mode")
_INT_KEYS = {"max_open_positions", "dedup_window_s", "session_start", "session_end",
             "max_trades_per_day", "max_consecutive_losses", "cooldown_after_loss_min",
             "trading_days_mask", "notify_trades", "notify_risk",
             "daily_report_hour", "min_quality_score", "streak_risk_scaling"}
_STR_KEYS = {"engine_timeframe", "auto_strategy", "entry_mode", "engine_symbols",
             "trading_mode"}


def _cast(key, value):
    if key in _STR_KEYS:
        return str(value)
    return int(value) if key in _INT_KEYS else float(value)


# ── Durable mirror (Supabase) ────────────────────────────────────────────────
# The local JSON file lives under HUB_DATA_DIR, which is EPHEMERAL on a free host
# without a mounted disk — so a redeploy wiped it and every login showed default
# settings. When SUPABASE_URL + SUPABASE_KEY are set we also mirror the overrides
# to Supabase, so they survive redeploys for free. Runtime settings are
# single-tenant, so one fixed key. Fail-closed: a Supabase hiccup never breaks
# the file path.
_MIRROR_USER = "__hub__"
_MIRROR_NS = "runtime-overrides"
_mirror_cache: dict = {"built": False, "store": None}


def _mirror():
    if not _mirror_cache["built"]:
        _mirror_cache["built"] = True
        try:
            from data.settings_store import make_settings_mirror
            _mirror_cache["store"] = make_settings_mirror()
        except Exception:  # noqa: BLE001 — never let persistence wiring break boot
            _mirror_cache["store"] = None
    return _mirror_cache["store"]


def _casted(data: dict) -> dict:
    return {k: _cast(k, v) for k, v in data.items() if k in EDITABLE}


def load_overrides(path: str) -> dict:
    # 1. fast local file cache
    try:
        p = Path(path)
        if p.exists():
            local = _casted(json.loads(p.read_text()))
            if local:
                return local
    except Exception:  # noqa: BLE001 — corrupt/missing file -> try the mirror
        pass
    # 2. durable Supabase mirror — restores real settings after an
    #    ephemeral-disk restart instead of reverting to defaults.
    m = _mirror()
    if m is not None:
        try:
            remote = m.get(_MIRROR_USER, _MIRROR_NS)
        except Exception:  # noqa: BLE001
            remote = None
        if remote:
            clean = _casted(remote)
            try:                                   # warm the local cache
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(clean, indent=2))
            except Exception:  # noqa: BLE001
                pass
            return clean
    return {}


def save_overrides(path: str, data: dict) -> None:
    clean = {k: _cast(k, data[k]) for k in EDITABLE if k in data}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, indent=2))
    m = _mirror()                                  # durable write (best-effort)
    if m is not None:
        try:
            m.set(_MIRROR_USER, _MIRROR_NS, clean)
        except Exception:  # noqa: BLE001
            pass
