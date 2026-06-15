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
    role: str = "operator"          # "admin" | "operator"
    created_at: datetime = field(default_factory=_now)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


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


@dataclass
class Bot:
    config: BotConfig
    runtime: BotRuntime = field(default_factory=BotRuntime)

    @property
    def id(self) -> str:
        return self.config.id
