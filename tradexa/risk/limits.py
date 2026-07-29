"""Risk limits — the configuration a RiskEngine enforces.

One frozen object rather than fifteen constructor arguments, so a limit set can
be built once, logged, versioned, diffed between environments, and attached to
a decision as evidence of what was in force when it was made. A rejection that
cannot say which limits produced it is unauditable.

Every limit defaults to something SAFE rather than something permissive. A
misconfigured field should make the engine stricter, not silently unlimited —
the failure mode of a forgotten setting must not be an unbounded position.

``0`` disables a limit throughout, deliberately and consistently: it reads as
"no cap" at every call site, and it means a partially-configured engine cannot
accidentally enforce a limit of zero and refuse everything.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class RiskLimits:
    """What the engine will and will not allow."""

    # ── sizing ──────────────────────────────────────────────────────────────
    #: Fraction of equity risked per trade at full conviction. 1% is the
    #: conventional default and the one the live pipeline uses.
    risk_per_trade_pct: float = 0.01
    #: Hard ceiling on risk per trade regardless of what sizing computes. The
    #: backstop for a modifier chain that multiplies its way somewhere absurd.
    max_risk_per_trade_pct: float = 0.02

    # ── account ─────────────────────────────────────────────────────────────
    #: Total risk across all open positions, as a fraction of equity.
    max_account_risk_pct: float = 0.06
    #: Peak-to-trough equity decline that halts new entries.
    max_drawdown_pct: float = 0.20

    # ── drawdown windows ────────────────────────────────────────────────────
    max_daily_loss_pct: float = 0.03
    max_weekly_loss_pct: float = 0.06

    # ── exposure ────────────────────────────────────────────────────────────
    #: Notional of ONE position as a fraction of equity.
    max_position_exposure_pct: float = 0.05
    #: Gross notional across the book.
    max_total_exposure_pct: float = 0.10
    max_open_positions: int = 3
    #: Positions in one correlation cluster, same direction. Three simultaneous
    #: crypto longs are not diversification; they are one 3x bet.
    max_correlated_positions: int = 2

    # ── leverage & margin ───────────────────────────────────────────────────
    max_leverage: float = 1.0
    #: Free margin that must remain AFTER the trade, as a fraction of equity.
    #: A trade that leaves zero buffer is one adverse tick from a liquidation.
    min_free_margin_pct: float = 0.20

    # ── volatility ──────────────────────────────────────────────────────────
    #: ATR as a fraction of price, above which position size is scaled down.
    #: Fixed-fraction sizing already adapts via the stop distance; this is the
    #: second-order adjustment for regimes where the whole market is unstable.
    volatility_reference_pct: float = 0.02
    #: Floor on the volatility scale factor, so a volatile market reduces size
    #: rather than reducing it to nothing. Sizing a valid signal to zero
    #: converts a "yes" into a "no" after the decision was already made.
    min_volatility_scale: float = 0.25
    #: ATR/price above which the market is refused outright.
    max_volatility_pct: float = 0.0        # 0 = no hard ceiling

    # ── time ────────────────────────────────────────────────────────────────
    #: UTC hours [start, end). 0-24 means always open.
    session_start_hour: int = 0
    session_end_hour: int = 24
    #: Bitmask, Monday = bit 0. 127 = every day.
    trading_days_mask: int = 127
    #: Minutes either side of a scheduled news event during which entries are
    #: refused. Spreads widen and stops slip; a strategy edge measured on
    #: normal conditions does not survive them.
    news_blackout_minutes: int = 0

    # ── metadata ────────────────────────────────────────────────────────────
    name: str = "default"
    notes: Mapping[str, Any] = field(default_factory=dict)

    def with_(self, **changes: Any) -> "RiskLimits":
        """A copy with fields replaced. Frozen limits mean an engine cannot
        have its constraints edited underneath it mid-decision."""
        return replace(self, **changes)

    def as_dict(self) -> dict[str, Any]:
        """For logging and for attaching to a decision as evidence."""
        from dataclasses import asdict
        return asdict(self)


#: A deliberately conservative preset. Used when nothing is configured, so an
#: unconfigured engine is restrictive rather than permissive.
CONSERVATIVE = RiskLimits(
    name="conservative",
    risk_per_trade_pct=0.005, max_risk_per_trade_pct=0.01,
    max_account_risk_pct=0.03, max_daily_loss_pct=0.02,
    max_weekly_loss_pct=0.04, max_open_positions=2,
    max_total_exposure_pct=0.06, min_free_margin_pct=0.40,
)

#: Exactly what the live SignalPipeline enforces today — no more.
#:
#: The rules the pipeline has NEVER had are explicitly disabled here: account
#: risk, leverage, margin, news blackout and volatility. That is what makes
#: this preset safe to route production through: with it, the engine's veto is
#: a SUBSET of checks the pipeline already applies, so adding it to the live
#: path cannot refuse a trade that used to pass.
#:
#: Turning those rules on is a separate, deliberate decision — see ``STRICT``.
#: Leaving them enabled here and calling it "parity" would have made the switch
#: a silent tightening of live risk, dressed as a refactor.
PIPELINE_PARITY = RiskLimits(
    name="pipeline_parity",
    risk_per_trade_pct=0.01, max_risk_per_trade_pct=0.02,
    max_drawdown_pct=0.20, max_open_positions=3,
    max_correlated_positions=2, max_position_exposure_pct=0.05,
    max_total_exposure_pct=0.10, max_daily_loss_pct=0.03,
    max_weekly_loss_pct=0.06,
    # not enforced by the pipeline today:
    max_account_risk_pct=0.0, max_leverage=0.0, min_free_margin_pct=0.0,
    news_blackout_minutes=0, max_volatility_pct=0.0,
    volatility_reference_pct=0.0,
)

#: Everything the engine can enforce, on. The upgrade path from parity: an
#: operator opts in once they want the guards the pipeline never had.
STRICT = RiskLimits(
    name="strict",
    risk_per_trade_pct=0.01, max_risk_per_trade_pct=0.02,
    max_account_risk_pct=0.06, max_drawdown_pct=0.20,
    max_daily_loss_pct=0.03, max_weekly_loss_pct=0.06,
    max_position_exposure_pct=0.05, max_total_exposure_pct=0.10,
    max_open_positions=3, max_correlated_positions=2,
    max_leverage=1.0, min_free_margin_pct=0.20,
    volatility_reference_pct=0.02, news_blackout_minutes=15,
)

__all__ = ["RiskLimits", "CONSERVATIVE", "PIPELINE_PARITY", "STRICT"]
