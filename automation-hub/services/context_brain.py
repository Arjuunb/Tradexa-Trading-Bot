"""Context-aware brain — the decisions finally consume the context.

The bot collects Fear & Greed, funding rates and BTC market structure, but
until now the Decision Brain ignored all of it. Three bounded modifiers
connect that context to trading — each one OFF by default and shipped only
behind validation (POST /research/validate-context proves them on YOUR real
candles before anything changes live behavior):

  cross-asset gate   altcoin longs are blocked while BTC's own trend is
                     bearish (and alt shorts while BTC is bullish) — alts
                     rarely fight BTC and win
  funding sizing     entering WITH an extremely crowded side (|funding| >=
                     0.05%/8h) trades at reduced size — squeeze insurance
  sentiment sizing   at Fear&Greed extremes, the with-crowd direction trades
                     at reduced size (shorting capitulation / buying euphoria
                     is the crowd's mistake)

Gates are graded by the counterfactual tracker like every other veto; sizing
factors are bounded [0.5, 1.0] and visible in the decision log.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

FUNDING_EXTREME = 0.05      # % per 8h
FG_FEAR, FG_GREED = 10, 90
SIZE_FACTOR = 0.5           # bounded floor for context sizing
_LEADER = "BTCUSDT"


@dataclass
class ContextConfig:
    cross_asset: bool = False
    funding: bool = False
    sentiment: bool = False

    @classmethod
    def from_env(cls) -> "ContextConfig":
        import os
        on = os.environ.get("HUB_CONTEXT", "").lower() in ("1", "true", "all")
        pick = os.environ.get("HUB_CONTEXT", "")
        return cls(cross_asset=on or "cross" in pick,
                   funding=on or "funding" in pick,
                   sentiment=on or "sentiment" in pick)

    @property
    def any_enabled(self) -> bool:
        return self.cross_asset or self.funding or self.sentiment


# ─────────────────────────── pure classifiers ───────────────────────────
def classify_trend(closes: list[float]) -> str:
    """BTC trend for the cross-asset gate: bearish / bullish / neutral."""
    if len(closes) < 55:
        return "neutral"
    from bot.data.indicators import ema
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)[-1]
    price = closes[-1]
    slope = e20[-1] - e20[-4]
    if price < e50 and slope < 0:
        return "bearish"
    if price > e50 and slope > 0:
        return "bullish"
    return "neutral"


def cross_asset_block(symbol: str, side: str, leader_trend: str) -> Optional[str]:
    """Reason to block an altcoin entry that fights BTC, else None."""
    if symbol.upper().startswith(_LEADER[:3]):
        return None                       # BTC trades on its own trend
    if side == "long" and leader_trend == "bearish":
        return f"BTC trend is bearish — altcoin longs stand aside ({symbol})"
    if side == "short" and leader_trend == "bullish":
        return f"BTC trend is bullish — altcoin shorts stand aside ({symbol})"
    return None


def funding_factor(side: str, funding_pct_8h: Optional[float]) -> float:
    """Reduced size when entering WITH an extremely crowded side."""
    if funding_pct_8h is None:
        return 1.0
    if side == "long" and funding_pct_8h >= FUNDING_EXTREME:
        return SIZE_FACTOR
    if side == "short" and funding_pct_8h <= -FUNDING_EXTREME:
        return SIZE_FACTOR
    return 1.0


def sentiment_factor(side: str, fear_greed: Optional[int]) -> float:
    """Reduced size for the with-crowd direction at sentiment extremes."""
    if fear_greed is None:
        return 1.0
    if side == "short" and fear_greed <= FG_FEAR:
        return SIZE_FACTOR                # shorting capitulation
    if side == "long" and fear_greed >= FG_GREED:
        return SIZE_FACTOR                # buying euphoria
    return 1.0


# ─────────────────────────── live adapter ───────────────────────────
class ContextModifiers:
    """Live wrapper: pulls leader bars / funding / sentiment through the
    existing cached fetchers and applies the pure rules above."""

    def __init__(self, config: Optional[ContextConfig] = None,
                 leader_bars_fn: Optional[Callable[[], list]] = None):
        self.config = config or ContextConfig.from_env()
        self._leader_bars_fn = leader_bars_fn

    def _leader_trend(self) -> str:
        try:
            bars = self._leader_bars_fn() if self._leader_bars_fn else []
            return classify_trend([b.close for b in bars])
        except Exception:  # noqa: BLE001 — no leader data -> no gate
            return "neutral"

    def gate(self, symbol: str, side: str) -> Optional[str]:
        if not self.config.cross_asset:
            return None
        return cross_asset_block(symbol, side, self._leader_trend())

    def size_factor(self, symbol: str, side: str) -> float:
        factor = 1.0
        if self.config.funding:
            try:
                from services.market_context import _cached, fetch_funding_rate
                f = _cached(f"funding:{symbol}", lambda: fetch_funding_rate(symbol), ttl=120)
                factor = min(factor, funding_factor(side, f.get("value")))
            except Exception:  # noqa: BLE001
                pass
        if self.config.sentiment:
            try:
                from services.market_context import _cached
                from services.sentiment import fetch_fear_greed
                fg = _cached("fear_greed_raw", fetch_fear_greed, ttl=300) or {}
                factor = min(factor, sentiment_factor(side, fg.get("value")))
            except Exception:  # noqa: BLE001
                pass
        return max(SIZE_FACTOR, factor)


# ─────────────────────────── validation harness ───────────────────────────
class _GatedStrategy:
    """Sim wrapper: drops signals that fight the leader's bar-aligned trend."""

    def __init__(self, inner, leader_trend_by_index: list[str]):
        self.inner = inner
        self._trends = leader_trend_by_index
        self._i = -1
        self.blocked = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def on_bar(self, bar):
        from bot.types import SignalType
        self._i += 1
        sig = self.inner.on_bar(bar)
        if sig is None:
            return None
        trend = self._trends[min(self._i, len(self._trends) - 1)]
        side = "long" if sig.type == SignalType.LONG else "short"
        if cross_asset_block(self.inner.symbol, side, trend):
            self.blocked += 1
            return None
        return sig


def leader_trend_series(leader_rows: list) -> list[str]:
    closes = [b.close for b in leader_rows]
    return [classify_trend(closes[: i + 1]) for i in range(len(closes))]


def validate_cross_asset(symbols=("ETHUSDT", "SOLUSDT", "XRPUSDT"),
                         timeframe: str = "1h", bars: int = 2500,
                         require_real: bool = True) -> dict:
    """Baseline vs BTC-gated run per altcoin on the SAME candles."""
    from data.market_data import get_bars
    from strategies.brain_strategy import DecisionBrain
    from strategies.custom import gated_sim

    leader_rows, _src = get_bars(_LEADER, n=bars, timeframe=timeframe,
                                 require_real=require_real)
    if not leader_rows or len(leader_rows) < 400:
        return {"available": False, "verdict": "no-real-data",
                "detail": "No BTC candles cached — run the data load first."}
    trends = leader_trend_series(leader_rows)

    per, base_total, gated_total = [], 0.0, 0.0
    for sym in symbols:
        rows, _s = get_bars(sym, n=bars, timeframe=timeframe, require_real=require_real)
        if not rows or len(rows) < 400:
            per.append({"symbol": sym, "note": "no data"})
            continue
        n = min(len(rows), len(trends))
        # PARITY: both runs go through the live quality gate (the modifier is
        # judged on top of the system that actually trades, not a bare brain)
        base = gated_sim(DecisionBrain(sym), rows[-n:])
        gated_strat = _GatedStrategy(DecisionBrain(sym), trends[-n:])
        gated = gated_sim(gated_strat, rows[-n:])
        base_total += base.get("net_r", 0.0)
        gated_total += gated.get("net_r", 0.0)
        per.append({"symbol": sym,
                    "baseline": {"trades": base.get("total_trades"), "net_r": base.get("net_r")},
                    "gated": {"trades": gated.get("total_trades"), "net_r": gated.get("net_r"),
                              "blocked_by_btc": gated_strat.blocked}})
    judged = [p for p in per if "baseline" in p]
    if not judged:
        return {"available": False, "verdict": "no-real-data",
                "detail": "No altcoin candles cached."}
    helps = gated_total > base_total + 1.0
    hurts = gated_total < base_total - 1.0
    verdict = "helps" if helps else "hurts" if hurts else "neutral"
    return {"available": True, "verdict": verdict,
            "net_r": {"baseline": round(base_total, 2), "gated": round(gated_total, 2)},
            "per_symbol": per,
            "recommendation": ("enable with HUB_CONTEXT=cross" if helps else
                               "leave disabled" if hurts else
                               "no material difference on this window")}


def _weighted_net(trades: list[dict], factor_by_day: dict[str, float]) -> float:
    total = 0.0
    for t in trades:
        day = (t.get("entry_time") or "")[:10]
        total += float(t.get("r") or 0.0) * factor_by_day.get(day, 1.0)
    return round(total, 2)


def validate_sizing_modifier(kind: str, factor_by_day: dict[str, float],
                             symbols=("BTCUSDT", "ETHUSDT"), timeframe: str = "1h",
                             bars: int = 2500, require_real: bool = True) -> dict:
    """Sizing modifiers only scale each trade's size, so their effect is the
    trade-R stream re-weighted by the entry-day factor — exact, not simulated."""
    from data.market_data import get_bars
    from strategies.brain_strategy import DecisionBrain
    from strategies.custom import gated_sim

    if not factor_by_day:
        return {"available": False, "verdict": "no-history",
                "detail": f"No {kind} history reachable — run on the deployed host."}
    base_total = weighted_total = 0.0
    n_trades = 0
    for sym in symbols:
        rows, _s = get_bars(sym, n=bars, timeframe=timeframe, require_real=require_real)
        if not rows or len(rows) < 400:
            continue
        res = gated_sim(DecisionBrain(sym), rows)
        trades = res.get("trades", [])
        n_trades += len(trades)
        base_total += sum(float(t.get("r") or 0.0) for t in trades)
        weighted_total += _weighted_net(trades, factor_by_day)
    if n_trades < 10:
        return {"available": False, "verdict": "no-real-data",
                "detail": "Not enough real trades to judge — load data first."}
    helps = weighted_total > base_total + 0.5
    hurts = weighted_total < base_total - 0.5
    verdict = "helps" if helps else "hurts" if hurts else "neutral"
    return {"available": True, "verdict": verdict, "trades": n_trades,
            "net_r": {"baseline": round(base_total, 2),
                      "with_modifier": round(weighted_total, 2)}}


def fetch_funding_history_factors(symbol: str = "BTCUSDT", get_json=None) -> dict[str, float]:
    """Daily sizing factors from Binance's public funding history (keyless)."""
    if get_json is None:
        from services.sentiment import _get_json as get_json  # type: ignore
    d = get_json(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1000")
    out: dict[str, float] = {}
    try:
        from datetime import datetime, timezone
        for row in d:
            day = datetime.fromtimestamp(row["fundingTime"] / 1000,
                                         tz=timezone.utc).date().isoformat()
            pct = float(row["fundingRate"]) * 100
            out[day] = min(out.get(day, 1.0), funding_factor("long", pct))
    except Exception:  # noqa: BLE001
        return {}
    return out


def fetch_sentiment_history_factors(side: str = "long", get_json=None) -> dict[str, float]:
    """Daily sizing factors from the full Fear & Greed history (keyless)."""
    if get_json is None:
        from services.sentiment import _get_json as get_json  # type: ignore
    d = get_json("https://api.alternative.me/fng/?limit=0&format=json")
    out: dict[str, float] = {}
    try:
        from datetime import datetime, timezone
        for row in d["data"]:
            day = datetime.fromtimestamp(int(row["timestamp"]),
                                         tz=timezone.utc).date().isoformat()
            out[day] = sentiment_factor(side, int(row["value"]))
    except Exception:  # noqa: BLE001
        return {}
    return out


def validate_context(timeframe: str = "1h", bars: int = 2500,
                     require_real: bool = True) -> dict:
    """The full gauntlet for all three modifiers, with per-modifier verdicts
    and enable recommendations. Nothing is enabled automatically."""
    cross = validate_cross_asset(timeframe=timeframe, bars=bars,
                                 require_real=require_real)
    funding = validate_sizing_modifier(
        "funding", fetch_funding_history_factors(), timeframe=timeframe,
        bars=bars, require_real=require_real)
    sentiment = validate_sizing_modifier(
        "sentiment", fetch_sentiment_history_factors("long"), timeframe=timeframe,
        bars=bars, require_real=require_real)
    return {"cross_asset": cross, "funding": funding, "sentiment": sentiment,
            "note": ("Modifiers stay OFF until you enable the validated ones via "
                     "HUB_CONTEXT (e.g. HUB_CONTEXT=cross or HUB_CONTEXT=1 for all).")}
