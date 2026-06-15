"""Portfolio Risk Engine (Phase 5 · portfolio-level capital protection)."""
from services.portfolio_risk import (
    PortfolioLimits, PortfolioRiskEngine, Position, positions_from_bots,
)


def _pos(symbol, strategy="ema", direction="long", notional=2000.0, risk=100.0):
    return Position(symbol, strategy, direction, notional, risk)


# ------------------------------------------------------------- aggregation
def test_snapshot_aggregates_by_symbol_strategy_direction():
    eng = PortfolioRiskEngine()
    positions = [
        _pos("BTC/USDT", "ema", "long", 3000, 150),
        _pos("ETH/USDT", "smc", "short", 2000, 100),
        _pos("BTC/USDT", "ema", "long", 1000, 50),
    ]
    s = eng.snapshot(10000, positions)
    assert s.total_notional == 6000 and abs(s.exposure_pct - 0.6) < 1e-9
    assert s.by_symbol["BTC/USDT"] == 4000
    assert s.by_strategy["ema"] == 4000 and s.by_strategy["smc"] == 2000
    assert s.by_direction["long"] == 4000 and s.by_direction["short"] == 2000
    assert s.open_risk == 300


# -------------------------------------------------------- portfolio exposure
def test_blocks_when_total_exposure_exceeds_cap():
    eng = PortfolioRiskEngine(PortfolioLimits(max_portfolio_exposure_pct=0.5))
    positions = [_pos("BTC/USDT", notional=4000)]
    # 4000 + 2000 = 6000 > 50% of 10000
    v = eng.check_new(10000, positions, _pos("ETH/USDT", notional=2000))
    assert not v.allowed
    assert any(c.rule == "max_portfolio_exposure" and not c.passed for c in v.checks)


def test_allows_within_all_limits():
    eng = PortfolioRiskEngine(PortfolioLimits(max_portfolio_exposure_pct=1.0))
    v = eng.check_new(10000, [_pos("BTC/USDT", notional=2000)], _pos("ETH/USDT", notional=2000))
    assert v.allowed and all(c.passed for c in v.checks)


# ----------------------------------------------------- strategy allocation
def test_blocks_when_strategy_allocation_exceeded():
    eng = PortfolioRiskEngine(PortfolioLimits(strategy_allocation={"ema": 0.4}))
    positions = [_pos("BTC/USDT", strategy="ema", notional=3500)]
    # ema would become 3500 + 1000 = 4500 > 40% of 10000
    v = eng.check_new(10000, positions, _pos("ETH/USDT", strategy="ema", notional=1000))
    assert not v.allowed
    assert any(c.rule == "strategy_allocation" and not c.passed for c in v.checks)


def test_strategy_without_allocation_is_unconstrained():
    eng = PortfolioRiskEngine(PortfolioLimits(strategy_allocation={"ema": 0.4}))
    v = eng.check_new(10000, [], _pos("ETH/USDT", strategy="smc", notional=9000))
    assert v.allowed                       # smc has no allocation cap (only exposure)


# ------------------------------------------------------- correlated trades
def test_blocks_too_many_correlated_trades():
    limits = PortfolioLimits(
        max_correlated_trades=2,
        correlation_groups={"BTC/USDT": "majors", "ETH/USDT": "majors", "SOL/USDT": "majors"},
    )
    eng = PortfolioRiskEngine(limits)
    positions = [_pos("BTC/USDT", notional=1000), _pos("ETH/USDT", notional=1000)]
    v = eng.check_new(10000, positions, _pos("SOL/USDT", notional=1000))
    assert not v.allowed
    assert any(c.rule == "max_correlated_trades" and not c.passed for c in v.checks)


def test_uncorrelated_symbols_allowed():
    eng = PortfolioRiskEngine(PortfolioLimits(max_correlated_trades=1))
    # no correlation_groups -> each symbol is its own group
    v = eng.check_new(10000, [_pos("BTC/USDT", notional=1000)], _pos("ETH/USDT", notional=1000))
    assert v.allowed


# ------------------------------------------------------------- adapter
def test_positions_from_bots_only_active():
    from bots.manager import BotManager
    from database.models import BotConfig, BotMode
    m = BotManager()
    b1 = m.create(BotConfig(name="A", strategy="ema", exchange="binance", symbol="BTCUSDT"))
    m.create(BotConfig(name="B", strategy="rsi", exchange="binance", symbol="ETHUSDT"))  # stopped/created
    m.start(b1.id)   # paper -> active
    positions = positions_from_bots(m.list(), equity=10000)
    assert len(positions) == 1 and positions[0].symbol == "BTCUSDT"
