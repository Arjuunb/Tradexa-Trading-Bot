"""Global settings for Automation Hub.

Values come from environment variables (loaded from a local ``.env`` if present)
with safe defaults so the app runs out of the box for development.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# All persistent state (ledger, market data, learning, settings) lives here.
# On cloud hosts the app directory is EPHEMERAL — attach a persistent disk and
# set HUB_DATA_DIR to its mount path so trade history and learned lessons
# survive redeploys. Individual HUB_*_PATH vars still override per-file.
DATA_DIR = Path(os.environ.get("HUB_DATA_DIR") or (BASE_DIR / "logs"))


def _load_dotenv(path: Path) -> None:
    """Tiny stdlib .env loader (no python-dotenv dependency)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


@dataclass
class Settings:
    # --- auth (Phase 1: single configured operator) ---
    username: str = field(default_factory=lambda: os.environ.get("HUB_USERNAME", "admin"))
    password: str = field(default_factory=lambda: os.environ.get("HUB_PASSWORD", "admin"))
    secret_key: str = field(default_factory=lambda: os.environ.get("HUB_SECRET", "dev-insecure-secret"))

    # --- display ---
    app_name: str = "Automation Hub"
    currency: str = field(default_factory=lambda: os.environ.get("HUB_CURRENCY", "£"))

    # --- defaults for new bots ---
    default_exchange: str = field(default_factory=lambda: os.environ.get("HUB_EXCHANGE", "binance"))
    default_symbol: str = "BTCUSDT"
    default_timeframe: str = "1h"
    starting_cash: float = field(default_factory=lambda: float(os.environ.get("HUB_STARTING_CASH", "10000")))

    # --- risk defaults ---
    risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3

    # --- persistence (Phase 6) ---
    db_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_DB_PATH", str(DATA_DIR / "hub.db")))

    # --- Kyros Phase 1: webhook + ledger ---
    webhook_secret: str = field(default_factory=lambda: os.environ.get("HUB_WEBHOOK_SECRET", "dev-webhook-secret"))
    exposure_limit_pct: float = field(default_factory=lambda: float(os.environ.get("HUB_EXPOSURE_LIMIT", "0.05")))
    ledger_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_LEDGER_PATH", str(DATA_DIR / "ledger.db")))
    dedup_window_s: int = field(default_factory=lambda: int(os.environ.get("HUB_DEDUP_WINDOW", "300")))

    # --- autonomous strategy engine (real signals -> paper execution) ---
    auto_engine: bool = field(default_factory=lambda: os.environ.get("HUB_AUTO_ENGINE", "1") not in ("0", "false", ""))
    auto_symbols: tuple = field(default_factory=lambda: tuple(
        s.strip() for s in os.environ.get("HUB_AUTO_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip()))
    auto_interval: float = field(default_factory=lambda: float(os.environ.get("HUB_AUTO_INTERVAL", "2.0")))
    auto_timeframe: str = field(default_factory=lambda: os.environ.get("HUB_AUTO_TIMEFRAME", "4h"))
    auto_strategy: str = field(default_factory=lambda: os.environ.get("HUB_AUTO_STRATEGY", "brain"))
    use_live_data: bool = field(default_factory=lambda: os.environ.get("HUB_USE_LIVE_DATA", "").lower() in ("1", "true", "yes"))
    live_poll_s: float = field(default_factory=lambda: float(os.environ.get("HUB_LIVE_POLL", "60")))

    # --- market-quality gate (fail-closed pre-trade safety) ---
    quality_min_stop_pct: float = field(default_factory=lambda: float(os.environ.get("HUB_QUALITY_MIN_STOP", "0.0005")))
    quality_max_stop_pct: float = field(default_factory=lambda: float(os.environ.get("HUB_QUALITY_MAX_STOP", "0.25")))
    quality_max_signal_age_s: float = field(default_factory=lambda: float(os.environ.get("HUB_QUALITY_MAX_AGE", "0")))
    quality_max_spread_bps: float = field(default_factory=lambda: float(os.environ.get("HUB_QUALITY_MAX_SPREAD", "0")))

    # --- automatic capital protection (drawdown circuit breaker) ---
    max_drawdown_pct: float = field(default_factory=lambda: float(os.environ.get("HUB_MAX_DRAWDOWN", "0.20")))
    # daily-loss kill switch (% of starting equity; 0 = disabled). Resets each UTC day.
    max_daily_loss_pct: float = field(default_factory=lambda: float(os.environ.get("HUB_MAX_DAILY_LOSS", "0")))
    # trading-session window in UTC hours (start inclusive, end exclusive). 0..24 = always.
    session_start: int = field(default_factory=lambda: int(os.environ.get("HUB_SESSION_START", "0")))
    session_end: int = field(default_factory=lambda: int(os.environ.get("HUB_SESSION_END", "24")))
    # more critical-risk guards (all 0 = disabled)
    max_weekly_loss_pct: float = field(default_factory=lambda: float(os.environ.get("HUB_MAX_WEEKLY_LOSS", "0")))
    max_trades_per_day: int = field(default_factory=lambda: int(os.environ.get("HUB_MAX_TRADES_DAY", "0")))
    max_consecutive_losses: int = field(default_factory=lambda: int(os.environ.get("HUB_MAX_CONSEC_LOSSES", "0")))
    cooldown_after_loss_min: int = field(default_factory=lambda: int(os.environ.get("HUB_COOLDOWN_MIN", "0")))
    # allowed trading days bitmask (bit 0=Mon .. 6=Sun). 127 = all days.
    trading_days_mask: int = field(default_factory=lambda: int(os.environ.get("HUB_TRADING_DAYS", "127")))
    settings_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_SETTINGS_PATH", str(DATA_DIR / "runtime_settings.json")))
    custom_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_CUSTOM_PATH", str(DATA_DIR / "custom_strategies.json")))
    # Evolution Engine stores
    lessons_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_LESSONS_PATH", str(DATA_DIR / "lessons.json")))
    upgrades_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_UPGRADES_PATH", str(DATA_DIR / "upgrades.json")))
    versions_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_VERSIONS_PATH", str(DATA_DIR / "strategy_versions.json")))
    # Historical market-data cache (real Binance candles)
    market_db: str = field(default_factory=lambda: os.environ.get(
        "HUB_MARKET_DB", str(DATA_DIR / "market_data.db")))
    # Decision-journal database (full explainable record of every trade)
    journal_db: str = field(default_factory=lambda: os.environ.get(
        "HUB_JOURNAL_DB", str(DATA_DIR / "journal.db")))
    # Safety-gate state (when the emergency-stop kill switch was last verified)
    safety_state_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_SAFETY_STATE", str(DATA_DIR / "safety_state.json")))
    # Skipped-trade log (every rejected setup: failed gate + market snapshot)
    skipped_db: str = field(default_factory=lambda: os.environ.get(
        "HUB_SKIPPED_DB", str(DATA_DIR / "skipped.db")))
    # Persistent paper-account state (initial capital + current equity snapshot)
    account_db: str = field(default_factory=lambda: os.environ.get(
        "HUB_ACCOUNT_DB", str(DATA_DIR / "account.db")))
    # Unified decision store (every accepted AND rejected trade decision)
    decisions_db: str = field(default_factory=lambda: os.environ.get(
        "HUB_DECISIONS_DB", str(DATA_DIR / "decisions.db")))
    # Permanent trade-memory store (remembers every trade forever unless deleted)
    trade_memory_db: str = field(default_factory=lambda: os.environ.get(
        "HUB_TRADE_MEMORY_DB", str(DATA_DIR / "trade_memory.db")))
    # Market-context provider API keys (UI-settable, local JSON)
    providers_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_PROVIDERS_PATH", str(DATA_DIR / "providers.json")))

    # --- notifications (Phase 5) ---
    telegram_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))


settings = Settings()
