"""Domain models for Automation Hub.

Phase 1 keeps these as plain dataclasses held in memory (see
``bots.manager.BotManager`` / ``data.storage``). The ``database/`` package is
where a real ORM (SQLAlchemy) + ``migrations/`` would land in a later phase —
the dataclasses below define the schema those tables will mirror.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class BotMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class BotState(str, Enum):
    CREATED = "Created"
    RUNNING = "Running"
    PAPER = "Paper Mode"
    PAUSED = "Paused"
    STOPPED = "Stopped"
    ERROR = "Error"


@dataclass
class User:
    username: str
    password_hash: str = ""
    salt: str = ""
    role: str = "operator"          # "owner" | "admin" | "operator" | "viewer"
    created_at: datetime = field(default_factory=_now)
    # Contact address, distinct from the login identity: most accounts here sign
    # up with an email AS the username, but an OAuth or admin-created account
    # need not, and password reset has to reach someone either way.
    email: Optional[str] = None
    email_verified: bool = False
    totp_secret: Optional[str] = None
    totp_enabled: bool = False
    # Last TOTP step accepted. A code stays valid for its whole 30s window, so
    # without this an observed code is replayable until the window closes.
    totp_last_step: Optional[int] = None

    @property
    def is_admin(self) -> bool:
        # owner is the top role (created at signup) and is admin-capable — it
        # must not be locked out of admin-only actions like user management.
        return self.role in ("admin", "owner")

    @property
    def contact_email(self) -> Optional[str]:
        """Where to write. Falls back to the username when that is itself an
        email, which is how every account created through signup looks."""
        if self.email:
            return self.email
        return self.username if "@" in (self.username or "") else None


@dataclass
class RiskRules:
    risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3
    max_drawdown_pct: float = 0.20
    max_consecutive_losses: int = 4


@dataclass
class BotConfig:
    name: str
    strategy: str            # registry key: "ema" | "rsi" | "smc"
    exchange: str            # registry key: "binance" | "bybit" | "alpaca"
    symbol: str = "BTCUSDT"
    timeframe: str = "1h"
    mode: BotMode = BotMode.PAPER
    risk: RiskRules = field(default_factory=RiskRules)
    starting_cash: float = 10_000.0
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)


@dataclass
class BotRuntime:
    """Mutable runtime state attached to a bot."""
    state: BotState = BotState.CREATED
    started_at: Optional[datetime] = None
    metrics: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    events: list = field(default_factory=list)
    pnl_today: float = 0.0
    last_error: Optional[str] = None
    halt_reason: Optional[str] = None   # set when a risk circuit-breaker trips
    health: dict = field(default_factory=dict)   # P4: self-monitoring snapshot
    decisions: list = field(default_factory=list)  # P2: decision-log records
    risk_mode: dict = field(default_factory=dict)  # P6: adaptive risk mode
    strategy_health: dict = field(default_factory=dict)  # P3: rolling health
    regime: dict = field(default_factory=dict)     # P4: market regime


@dataclass
class Bot:
    config: BotConfig
    runtime: BotRuntime = field(default_factory=BotRuntime)

    @property
    def id(self) -> str:
        return self.config.id
