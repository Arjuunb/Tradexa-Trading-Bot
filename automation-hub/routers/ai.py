"""AI Trading Intelligence endpoints.

On-demand pre-trade analysis (`/ai/analyze`), the auto-updating trader profile
(`/ai/profile`), and the confidence legend. All compose the engine's existing
intelligence — nothing here re-implements strategy, risk or memory logic.
"""
import webhook_api as _wa
from fastapi import APIRouter, Query
from typing import Optional

from services import ai_intelligence as _ai

router = APIRouter()


@router.get("/ai/analyze")
def ai_analyze(symbol: str = "BTCUSDT", timeframe: str = "1h",
               side: Optional[str] = Query(None, description="long|short — omit to infer from bias"),
               leverage: float = 1.0,
               min_score: Optional[int] = None):
    """Full AI pre-trade analysis for a symbol: five-category setup score,
    confidence level, BUY/SELL/WAIT/SKIP with reasons, and the risk analysis.

    Cached briefly (per symbol/timeframe/side/leverage) so repeated dashboard
    polls don't re-run the read or re-fetch candles."""
    from data.market_data import get_bars
    from services.ttl_cache import cached

    equity = _wa.paper.balance()
    risk_pct = getattr(_wa.pipeline, "risk_per_trade_pct", None) or getattr(_wa.settings, "risk_per_trade_pct", 0.01)
    ms = int(min_score if min_score is not None else getattr(_wa.engine, "min_quality_score", 60) or 60)
    key = f"ai:analyze:{symbol}:{timeframe}:{side}:{leverage}:{ms}:{round(equity, 2)}"

    def _run() -> dict:
        bars, source = get_bars(symbol, n=250, timeframe=timeframe)
        if not bars:
            return {"available": False, "symbol": symbol, "note": "no market data"}
        out = _ai.analyze_setup(symbol=symbol, timeframe=timeframe, bars=bars, side=side,
                                equity=equity, risk_pct=float(risk_pct), min_score=ms,
                                leverage=float(leverage))
        out["available"] = True
        out["data_source"] = source
        return out

    return cached(key, 20.0, _run)


@router.get("/ai/profile")
def ai_profile():
    """The trader's personal profile (strengths / weaknesses), distilled from the
    trade-memory pattern-recognition insights — updates as trades close."""
    try:
        insights = _wa.trade_memory.insights()
    except Exception:  # noqa: BLE001 — no memory yet -> empty profile
        insights = {}
    return _ai.trader_profile(insights)


@router.get("/ai/confidence-accuracy")
def ai_confidence_accuracy():
    """Confidence calibration: do higher-confidence setups actually win more?
    Computed from the closed-trade memory (real outcomes)."""
    try:
        rows = _wa.trade_memory.store.list(limit=100000)
    except Exception:  # noqa: BLE001
        rows = []
    return _ai.confidence_accuracy(rows)


@router.get("/ai/confidence-levels")
def ai_confidence_levels():
    """Static legend: the score band each confidence level maps to."""
    return {"levels": [
        {"level": "Very High", "min_score": 85},
        {"level": "High", "min_score": 70},
        {"level": "Medium", "min_score": 55},
        {"level": "Low", "min_score": 40},
        {"level": "Very Low", "min_score": 0},
    ]}
