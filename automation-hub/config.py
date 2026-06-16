"""Global settings for Automation Hub.

Values come from environment variables (loaded from a local ``.env`` if present)
with safe defaults so the app runs out of the box for development.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


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
        "HUB_DB_PATH", str(BASE_DIR / "logs" / "hub.db")))

    # --- Kyros Phase 1: webhook + ledger ---
    webhook_secret: str = field(default_factory=lambda: os.environ.get("HUB_WEBHOOK_SECRET", "dev-webhook-secret"))
    exposure_limit_pct: float = field(default_factory=lambda: float(os.environ.get("HUB_EXPOSURE_LIMIT", "0.05")))
    ledger_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_LEDGER_PATH", str(BASE_DIR / "logs" / "ledger.db")))
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
    settings_path: str = field(default_factory=lambda: os.environ.get(
        "HUB_SETTINGS_PATH", str(BASE_DIR / "logs" / "runtime_settings.json")))

    # --- notifications (Phase 5) ---
    telegram_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))


settings = Settings()
