"""Portfolio Risk Engine (Phase 5 · capital protection).

Per-bot risk (``bot.risk`` / ``risk.guards``) protects one strategy. This engine
protects the *whole account*: it aggregates exposure across every bot and blocks
a new trade that would breach a portfolio-level limit.

Tracks: total exposure, exposure by symbol / strategy / direction, correlated
positions and open risk. Enforces: max portfolio exposure, max correlated
trades (per correlation group), and per-strategy capital-allocation limits.

Pure and dependency-free (no engine/execution coupling) so it is fully testable;
a thin adapter (``positions_from_bots``) builds positions from running bots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuleCheck:
    rule: str
    passed: bool
    detail: str = ""


@dataclass
class Position:
    symbol: str
    strategy: str
    direction: str           # "long" | "short"
    notional: float          # position size in account currency
    risk: float = 0.0        # open risk (distance to stop * size)


@dataclass
class PortfolioLimits:
    max_portfolio_exposure_pct: float = 1.0          # total notional / equity
    max_correlated_trades: int = 3                   # positions per correlation group
    strategy_allocation: dict[str, float] = field(default_factory=dict)  # strategy -> max fraction (0..1)
    correlation_groups: dict[str, str] = field(default_factory=dict)     # symbol -> group


@dataclass
class ExposureSnapshot:
    equity: float
    total_notional: float
    exposure_pct: float
    open_risk: float
    by_symbol: dict[str, float]
    by_strategy: dict[str, float]
    by_direction: dict[str, float]


@dataclass
class PortfolioVerdict:
    allowed: bool
    reason: str
    checks: list[RuleCheck] = field(default_factory=list)


class PortfolioRiskEngine:
    def __init__(self, limits: Optional[PortfolioLimits] = None):
        self.limits = limits or PortfolioLimits()

    def _group(self, symbol: str) -> str:
        return self.limits.correlation_groups.get(symbol, symbol)

    # ----------------------------------------------------------- aggregation
    def snapshot(self, equity: float, positions: list[Position]) -> ExposureSnapshot:
        by_symbol: dict[str, float] = {}
        by_strategy: dict[str, float] = {}
        by_direction: dict[str, float] = {}
        total = 0.0
        open_risk = 0.0
        for p in positions:
            total += p.notional
            open_risk += p.risk
            by_symbol[p.symbol] = by_symbol.get(p.symbol, 0.0) + p.notional
            by_strategy[p.strategy] = by_strategy.get(p.strategy, 0.0) + p.notional
            by_direction[p.direction] = by_direction.get(p.direction, 0.0) + p.notional
        return ExposureSnapshot(
            equity=equity, total_notional=total,
            exposure_pct=(total / equity) if equity > 0 else 0.0,
            open_risk=open_risk, by_symbol=by_symbol,
            by_strategy=by_strategy, by_direction=by_direction,
        )

    # --------------------------------------------------------- pre-trade gate
    def check_new(self, equity: float, positions: list[Position],
                  candidate: Position) -> PortfolioVerdict:
        """Would adding ``candidate`` breach a portfolio limit?"""
        lim = self.limits
        snap = self.snapshot(equity, positions)
        checks: list[RuleCheck] = []

        # 1. total portfolio exposure
        new_total = snap.total_notional + candidate.notional
        cap = lim.max_portfolio_exposure_pct * equity
        ok = new_total <= cap + 1e-9
        checks.append(RuleCheck(
            "max_portfolio_exposure", ok,
            f"{new_total/equity*100:.0f}% {'<=' if ok else '>'} {lim.max_portfolio_exposure_pct*100:.0f}% cap"))

        # 2. per-strategy allocation
        alloc = lim.strategy_allocation.get(candidate.strategy)
        if alloc is not None:
            new_strat = snap.by_strategy.get(candidate.strategy, 0.0) + candidate.notional
            scap = alloc * equity
            sok = new_strat <= scap + 1e-9
            checks.append(RuleCheck(
                "strategy_allocation", sok,
                f"{candidate.strategy} {new_strat/equity*100:.0f}% {'<=' if sok else '>'} {alloc*100:.0f}% allocation"))

        # 3. correlated trades (per correlation group)
        grp = self._group(candidate.symbol)
        in_group = sum(1 for p in positions if self._group(p.symbol) == grp)
        cok = in_group + 1 <= lim.max_correlated_trades
        checks.append(RuleCheck(
            "max_correlated_trades", cok,
            f"{in_group + 1} {'<=' if cok else '>'} {lim.max_correlated_trades} correlated ({grp})"))

        failed = [c for c in checks if not c.passed]
        if failed:
            return PortfolioVerdict(False, failed[0].detail, checks)
        return PortfolioVerdict(True, "within all portfolio limits", checks)


def positions_from_bots(bots, equity: float, leverage: float = 10.0) -> list[Position]:
    """Adapter: approximate open positions from running bots (notional derived
    from each bot's risk-per-trade). For precise notional, the live runner can
    supply real broker positions instead."""
    from database.models import BotState
    active = {BotState.RUNNING, BotState.PAPER}
    out: list[Position] = []
    for b in bots:
        if b.runtime.state not in active:
            continue
        risk = equity * b.config.risk.risk_per_trade_pct
        out.append(Position(
            symbol=b.config.symbol, strategy=b.config.strategy,
            direction="long", notional=risk * leverage, risk=risk,
        ))
    return out
