"""The Portfolio Engine — one view of capital across every broker and exchange.

    from tradexa.portfolio import Portfolio, PortfolioEngine, VenueSnapshot

    state = PortfolioEngine().snapshot(Portfolio(venues=[binance, ibkr]))
    state.equity, state.buying_power, state.sharpe_ratio

Separate from the execution engine on purpose. Execution knows how to place an
order at one venue; the portfolio has to answer "how much do I have, and how
exposed am I?" across all of them at once — a question no single execution
engine can answer, and one that would be reimplemented per broker if it lived
inside them.
"""
from tradexa.portfolio.engine import PortfolioEngine, PortfolioState, VenueState
from tradexa.portfolio.metrics import (
    DAYS_PER_YEAR, daily_closes, daily_return, expectancy, max_drawdown_pct,
    monthly_return, profit_factor, realized_pnl, sharpe_ratio, win_rate,
    window_return,
)
from tradexa.portfolio.snapshots import (
    ClosedTrade, Direction, EquityPoint, Portfolio, PositionSnapshot,
    VenueKind, VenueSnapshot,
)

__all__ = [
    "PortfolioEngine", "PortfolioState", "VenueState",
    "Portfolio", "VenueSnapshot", "PositionSnapshot", "EquityPoint",
    "ClosedTrade", "Direction", "VenueKind",
    "DAYS_PER_YEAR", "daily_closes", "daily_return", "monthly_return",
    "window_return", "max_drawdown_pct", "sharpe_ratio", "win_rate",
    "expectancy", "realized_pnl", "profit_factor",
]
