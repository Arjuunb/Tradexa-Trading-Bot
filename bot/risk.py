"""Risk management.

Responsibilities
----------------
1. Position sizing — risk a fixed % of equity per trade, derived from the
   distance between entry and stop loss.
2. Hard limits — max open positions, max daily loss, cooldown after stop-outs.
3. Pre-trade veto — returns (allow, qty, reason).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from bot.types import AccountSnapshot, Signal


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.01        # 1% of equity per trade
    max_open_positions: int = 3
    max_daily_loss_pct: float = 0.03        # halt for the day after -3%
    max_position_pct: float = 0.25          # cap notional at 25% of equity
    cooldown_bars_after_loss: int = 5


@dataclass
class RiskState:
    day: date = field(default_factory=lambda: date.today())
    starting_equity_today: float = 0.0
    realized_pnl_today: float = 0.0
    last_loss_time: Optional[datetime] = None
    cooldown_left: int = 0


class RiskManager:
    def __init__(self, config: RiskConfig | None = None):
        self.cfg = config or RiskConfig()
        self.state = RiskState()

    # ------------------------------------------------------ day rollover
    def _maybe_rollover(self, equity: float, now: datetime) -> None:
        today = now.date()
        if today != self.state.day:
            self.state = RiskState(day=today, starting_equity_today=equity)
        elif self.state.starting_equity_today == 0:
            self.state.starting_equity_today = equity

    # ---------------------------------------------------- pre-trade check
    def evaluate(
        self,
        signal: Signal,
        account: AccountSnapshot,
        now: datetime,
    ) -> tuple[bool, float, str]:
        self._maybe_rollover(account.equity, now)

        # Daily loss kill switch
        if self.state.starting_equity_today > 0:
            dd = (account.equity - self.state.starting_equity_today) / self.state.starting_equity_today
            if dd <= -self.cfg.max_daily_loss_pct:
                return False, 0.0, f"Daily loss limit hit ({dd:.2%})"

        # Cooldown
        if self.state.cooldown_left > 0:
            self.state.cooldown_left -= 1
            return False, 0.0, f"Cooldown active ({self.state.cooldown_left} bars left)"

        # Max open positions
        if len(account.positions) >= self.cfg.max_open_positions:
            return False, 0.0, "Max open positions reached"

        # Position sizing from risk distance
        risk_dollars = account.equity * self.cfg.risk_per_trade_pct
        risk_per_unit = abs(signal.entry - signal.stop_loss)
        if risk_per_unit <= 0:
            return False, 0.0, "Invalid stop loss (zero distance)"
        qty = risk_dollars / risk_per_unit

        # Cap notional
        max_notional = account.equity * self.cfg.max_position_pct
        if qty * signal.entry > max_notional:
            qty = max_notional / signal.entry

        if qty <= 0:
            return False, 0.0, "Computed qty <= 0"

        return True, qty, "ok"

    # ------------------------------------------------------ post-trade
    def on_trade_closed(self, pnl: float, now: datetime) -> None:
        self.state.realized_pnl_today += pnl
        if pnl < 0:
            self.state.last_loss_time = now
            self.state.cooldown_left = self.cfg.cooldown_bars_after_loss
