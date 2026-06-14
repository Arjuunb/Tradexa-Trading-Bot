"""Risk management.

Responsibilities
----------------
1. Position sizing — risk a fixed % of equity per trade, derived from the
   distance between entry and stop loss.
2. Hard limits — max open positions, max daily loss, cooldown after stop-outs.
3. Pre-trade veto — returns (allow, qty, reason).

Bar hook
--------
Callers (backtester and live runner) MUST call ``on_bar(equity, bar_time)``
once per bar. This is what advances cooldown counters and rolls the daily
loss anchor over to a true day boundary — not the first signal of the day.
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
    # ATR-based sizing (opt-in). When atr_stop_mult > 0, the risk manager will
    # use an ATR-derived stop distance *if it is wider than* the signal's own
    # stop — i.e. it can only make sizing MORE conservative, never less.
    atr_stop_mult: float = 0.0
    atr_period: int = 14

    def __post_init__(self) -> None:
        if not 0 < self.risk_per_trade_pct <= 1:
            raise ValueError("risk_per_trade_pct must be in (0, 1]")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1")
        if not 0 < self.max_daily_loss_pct <= 1:
            raise ValueError("max_daily_loss_pct must be in (0, 1]")
        if not 0 < self.max_position_pct <= 1:
            raise ValueError("max_position_pct must be in (0, 1]")
        if self.cooldown_bars_after_loss < 0:
            raise ValueError("cooldown_bars_after_loss must be >= 0")
        if self.atr_stop_mult < 0:
            raise ValueError("atr_stop_mult must be >= 0")
        if self.atr_period < 1:
            raise ValueError("atr_period must be >= 1")


@dataclass
class RiskState:
    day: Optional[date] = None
    starting_equity_today: float = 0.0
    realized_pnl_today: float = 0.0
    last_loss_time: Optional[datetime] = None
    cooldown_left: int = 0


class RiskManager:
    def __init__(self, config: RiskConfig | None = None):
        self.cfg = config or RiskConfig()
        self.state = RiskState()
        self._atr_cache: float = 0.0  # last ATR fed via update_atr()

    def update_atr(self, atr_value: float) -> None:
        """Feed the latest ATR (in price units) for ATR-based stop widening.

        Callers (backtester / live runner) compute ATR from the bar history
        they already hold and push it in here. Stays out of the hot path of
        evaluate() which must remain side-effect-free.
        """
        if atr_value < 0:
            raise ValueError("atr_value must be >= 0")
        self._atr_cache = atr_value

    # ------------------------------------------------------ bar hook
    def on_bar(self, equity: float, bar_time: datetime) -> None:
        """Per-bar housekeeping. Call once per bar before any evaluate().

        - Decrements cooldown so it is measured in BARS, not signals.
        - Anchors starting_equity_today at the true daily rollover.
        """
        today = bar_time.date()
        if self.state.day is None:
            # First bar ever — anchor to its date.
            self.state.day = today
            self.state.starting_equity_today = equity
        elif today != self.state.day:
            # New day — reset all daily state, equity anchored at day's first bar.
            self.state = RiskState(day=today, starting_equity_today=equity)

        if self.state.cooldown_left > 0:
            self.state.cooldown_left -= 1

    # ---------------------------------------------------- pre-trade check
    def evaluate(
        self,
        signal: Signal,
        account: AccountSnapshot,
        now: datetime,
    ) -> tuple[bool, float, str]:
        """Returns (allow, qty, reason). Does NOT advance cooldown — on_bar does."""
        # Defensive: if caller forgot on_bar, anchor today now (no rollover here).
        if self.state.day is None:
            self.state.day = now.date()
            self.state.starting_equity_today = account.equity

        # Daily loss kill switch (uses anchored open equity).
        if self.state.starting_equity_today > 0:
            dd = (account.equity - self.state.starting_equity_today) / self.state.starting_equity_today
            if dd <= -self.cfg.max_daily_loss_pct:
                return False, 0.0, f"Daily loss limit hit ({dd:.2%})"

        # Cooldown after a stop-out — measured in bars via on_bar.
        if self.state.cooldown_left > 0:
            return False, 0.0, f"Cooldown active ({self.state.cooldown_left} bars left)"

        # Max open positions
        if len(account.positions) >= self.cfg.max_open_positions:
            return False, 0.0, "Max open positions reached"

        # Risk-based position sizing
        risk_dollars = account.equity * self.cfg.risk_per_trade_pct
        risk_per_unit = abs(signal.entry - signal.stop_loss)
        if risk_per_unit <= 0:
            return False, 0.0, "Invalid stop loss (zero distance to entry)"

        # If ATR sizing is enabled and the implied ATR-stop is WIDER than the
        # signal's stop, use it. This only ever reduces qty (more conservative).
        if self.cfg.atr_stop_mult > 0 and self._atr_cache > 0:
            atr_stop = self.cfg.atr_stop_mult * self._atr_cache
            if atr_stop > risk_per_unit:
                risk_per_unit = atr_stop

        qty = risk_dollars / risk_per_unit

        # Cap notional
        max_notional = account.equity * self.cfg.max_position_pct
        if signal.entry > 0 and qty * signal.entry > max_notional:
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
