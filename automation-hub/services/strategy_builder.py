"""No-Code Strategy Builder — catalog, templates and AI review.

Pure orchestration over the EXISTING spec engine (strategies/custom.py). The
visual builder produces the same JSON spec that ``simulate`` / the paper engine
already run, so there is no second execution path. This module just:

  * describes the available blocks (so the palette is data-driven),
  * ships ready-made templates as specs,
  * and reviews a spec (complexity / risk / strengths / confidence) by reusing
    the simulator's own results — never inventing numbers.
"""
from __future__ import annotations

from typing import Optional

_N = "number"
_S = "select"


def _p(name, default, type_=_N, options=None, label=None):
    d = {"name": name, "type": type_, "default": default, "label": label or name}
    if options:
        d["options"] = options
    return d


_ABOVE_BELOW = [_p("dir", "above", _S, ["above", "below"])]
_UP_DOWN = [_p("dir", "up", _S, ["up", "down"])]

# Rule blocks, grouped into the builder's categories. Every ``type`` maps 1:1 to
# a branch in strategies.custom._rule — the builder can't invent behaviour.
CATEGORIES = [
    {"key": "market_structure", "label": "Market Structure", "blocks": [
        {"type": "trend", "label": "Trend Direction (HH/HL)", "desc": "Market structure trending up (HH/HL) or down (LH/LL).",
         "params": [_p("pivot", 3), _p("lookback", 60)] + _UP_DOWN},
        {"type": "bos", "label": "Break of Structure", "desc": "Close breaks the last swing high/low.",
         "params": [_p("pivot", 3)] + _UP_DOWN},
        {"type": "support_bounce", "label": "Support / Resistance", "desc": "Price reacts at a recent support or resistance level.",
         "params": [_p("lookback", 30), _p("tolerance_pct", 0.5),
                    _p("dir", "support", _S, ["support", "resistance"])]},
    ]},
    {"key": "smc", "label": "Smart Money Concepts", "blocks": [
        {"type": "choch", "label": "Change of Character", "desc": "Reversal break of structure against the prior trend.",
         "params": [_p("pivot", 3)] + _UP_DOWN},
        {"type": "liquidity_sweep", "label": "Liquidity Sweep", "desc": "Wick beyond a recent extreme then reclaim (stop hunt).",
         "params": [_p("lookback", 20), _p("dir", "down", _S, ["down", "up"])]},
        {"type": "fair_value_gap", "label": "Fair Value Gap", "desc": "3-candle imbalance (FVG).",
         "params": _UP_DOWN},
    ]},
    {"key": "indicators", "label": "Indicators", "blocks": [
        {"type": "ema_cross", "label": "EMA Crossover", "desc": "Fast EMA above/below slow EMA.",
         "params": [_p("fast", 20), _p("slow", 50)] + _ABOVE_BELOW},
        {"type": "sma_trend", "label": "SMA Trend", "desc": "Price above/below a moving average.",
         "params": [_p("period", 200)] + _ABOVE_BELOW},
        {"type": "rsi", "label": "RSI", "desc": "Relative Strength Index above/below a level.",
         "params": [_p("period", 14), _p("value", 50), _p("op", "above", _S, ["above", "below"])]},
        {"type": "macd", "label": "MACD", "desc": "MACD line above/below its signal.",
         "params": [_p("fast", 12), _p("slow", 26), _p("signal", 9)] + _ABOVE_BELOW},
        {"type": "vwap", "label": "VWAP", "desc": "Price above/below the rolling VWAP.",
         "params": [_p("period", 20)] + _ABOVE_BELOW},
        {"type": "bollinger", "label": "Bollinger Bands", "desc": "Price relative to the bands.",
         "params": [_p("period", 20), _p("std", 2),
                    _p("zone", "below_lower", _S, ["below_lower", "above_upper", "above_mid", "below_mid"])]},
        {"type": "atr_filter", "label": "ATR (Volatility)", "desc": "Volatility filter — ATR as % of price.",
         "params": [_p("period", 14), _p("value_pct", 4), _p("op", "below", _S, ["below", "above"])]},
        {"type": "adx", "label": "ADX (Trend Strength)", "desc": "Average Directional Index above/below a level.",
         "params": [_p("period", 14), _p("value", 25), _p("op", "above", _S, ["above", "below"])]},
        {"type": "supertrend", "label": "Supertrend", "desc": "ATR Supertrend direction.",
         "params": [_p("period", 10), _p("mult", 3)] + _UP_DOWN},
        {"type": "stoch_rsi", "label": "Stochastic RSI", "desc": "StochRSI oversold/overbought.",
         "params": [_p("period", 14), _p("value", 20), _p("op", "below", _S, ["below", "above"])]},
        {"type": "obv", "label": "OBV (Volume)", "desc": "On-Balance Volume rising/falling.",
         "params": [_p("lookback", 20)] + _UP_DOWN},
        {"type": "volume", "label": "Volume vs Average", "desc": "Volume above/below its average.",
         "params": [_p("period", 20), _p("op", "above", _S, ["above", "below"])]},
    ]},
    {"key": "price_action", "label": "Price Action", "blocks": [
        {"type": "breakout", "label": "Breakout", "desc": "Close breaks the N-bar high/low.",
         "params": [_p("lookback", 20)] + _UP_DOWN},
        {"type": "pullback", "label": "Pullback to MA", "desc": "Price pulls back to a moving average in-trend.",
         "params": [_p("period", 20)] + _UP_DOWN},
    ]},
]

# Config sections (spec-level, not entry-tree rules).
CONFIG = {
    "logic": ["AND", "OR", "NOT"],
    "risk": [
        _p("risk_per_trade_pct", 0.01), _p("max_trades_per_day", 0),
        _p("max_consecutive_losses", 0), _p("cooldown_after_loss", 0),
    ],
    "stop": [_p("type", "atr", _S, ["atr", "pct"]), _p("mult", 1.5), _p("period", 14), _p("pct", 2)],
    "target": [_p("type", "rr", _S, ["rr", "pct"]), _p("rr", 2), _p("pct", 3)],
    "exit": [_p("breakeven_at_r", 0), _p("trail_atr", 0), _p("time_stop_bars", 0)],
    "sessions": [
        {"key": "any", "label": "Any", "start": 0, "end": 24},
        {"key": "london", "label": "London", "start": 7, "end": 16},
        {"key": "new_york", "label": "New York", "start": 12, "end": 21},
        {"key": "tokyo", "label": "Tokyo", "start": 0, "end": 9},
        {"key": "sydney", "label": "Sydney", "start": 21, "end": 6},
    ],
}


def block_catalog() -> dict:
    return {"categories": CATEGORIES, "config": CONFIG}


# ─────────────────────────── templates ───────────────────────────
def _tmpl(id_, name, desc, side, rules, **spec) -> dict:
    return {"id": id_, "name": name, "description": desc, "template": True,
            "side": side, "entry": {"op": "AND", "rules": rules},
            "stop": spec.get("stop", {"type": "atr", "mult": 1.5, "period": 14}),
            "target": spec.get("target", {"type": "rr", "rr": 2}),
            "risk_per_trade_pct": spec.get("risk_per_trade_pct", 0.01),
            **{k: v for k, v in spec.items() if k not in ("stop", "target", "risk_per_trade_pct")}}


def templates() -> list[dict]:
    return [
        _tmpl("smc", "Smart Money Concepts", "BOS + liquidity sweep + FVG in a trend.", "long",
              [{"type": "trend", "dir": "up"}, {"type": "liquidity_sweep", "dir": "down"},
               {"type": "bos", "dir": "up"}], target={"type": "rr", "rr": 3}),
        _tmpl("ict", "ICT", "Liquidity sweep into a fair-value gap, structure-aligned.", "long",
              [{"type": "liquidity_sweep", "dir": "down"}, {"type": "fair_value_gap", "dir": "up"},
               {"type": "choch", "dir": "up"}], target={"type": "rr", "rr": 3}),
        _tmpl("price_action", "Price Action", "Break-and-retest with a support bounce.", "long",
              [{"type": "breakout", "dir": "up"}, {"type": "support_bounce", "dir": "support"}]),
        _tmpl("ema_trend", "EMA Trend Following", "EMA20 > EMA50 with price above the 200 SMA.", "long",
              [{"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"},
               {"type": "sma_trend", "period": 200, "dir": "above"}]),
        _tmpl("breakout", "Breakout", "20-bar breakout confirmed by rising volume.", "long",
              [{"type": "breakout", "lookback": 20, "dir": "up"}, {"type": "volume", "op": "above"}]),
        _tmpl("scalping", "Scalping", "Fast EMA cross + StochRSI oversold, tight target.", "long",
              [{"type": "ema_cross", "fast": 9, "slow": 21, "dir": "above"},
               {"type": "stoch_rsi", "op": "below", "value": 20}],
              target={"type": "rr", "rr": 1.5}, max_trades_per_day=6),
        _tmpl("swing", "Swing Trading", "Higher-timeframe trend + pullback to the 50 EMA.", "long",
              [{"type": "trend", "dir": "up"}, {"type": "pullback", "period": 50, "dir": "up"}],
              target={"type": "rr", "rr": 3}),
        _tmpl("mean_reversion", "Mean Reversion", "RSI oversold at the lower Bollinger band.", "long",
              [{"type": "rsi", "op": "below", "value": 30}, {"type": "bollinger", "zone": "below_lower"}],
              target={"type": "rr", "rr": 1.5}),
        _tmpl("momentum", "Momentum", "MACD > signal with strong ADX and rising OBV.", "long",
              [{"type": "macd", "dir": "above"}, {"type": "adx", "op": "above", "value": 25},
               {"type": "obv", "dir": "up"}]),
        _tmpl("trend_following", "Trend Following", "Supertrend up with EMA alignment.", "long",
              [{"type": "supertrend", "dir": "up"}, {"type": "ema_cross", "fast": 20, "slow": 50, "dir": "above"}],
              target={"type": "rr", "rr": 3}),
    ]


# ─────────────────────────── AI strategy review ───────────────────────────
def _count_rules(tree: dict) -> int:
    return len(tree.get("rules") or [])


def ai_review(spec: dict, results: Optional[dict] = None) -> dict:
    """Analyse a strategy spec: complexity, risk, expected behaviour, strengths,
    weaknesses, improvements, and an estimated confidence. Uses the simulator's
    real results when provided — nothing is invented."""
    from services.ai_intelligence import confidence_level
    from strategies.custom import validate, describe

    rules = _count_rules(spec.get("entry") or {})
    risk_pct = float(spec.get("risk_per_trade_pct", 0.01))
    exit_cfg = spec.get("exit") or {}
    has_be = bool(exit_cfg.get("breakeven_at_r"))
    has_trail = bool(exit_cfg.get("trail_atr"))
    target = spec.get("target") or {}
    rr = float(target.get("rr", 0)) if target.get("type") == "rr" else None

    complexity = "simple" if rules <= 2 else "moderate" if rules <= 4 else "complex"
    risk_level = ("high" if risk_pct > 0.03 else "elevated" if risk_pct > 0.015 else "conservative")

    strengths, weaknesses, improvements = [], [], []
    if rr and rr >= 2:
        strengths.append(f"Healthy reward:risk target ({rr:.1f}R).")
    elif rr is not None and rr < 1.5:
        weaknesses.append(f"Low reward:risk ({rr:.1f}R) — wins may not cover losses.")
    if has_be or has_trail:
        strengths.append("Active trade management (break-even / trailing) protects winners.")
    else:
        improvements.append("Add break-even or a trailing stop to protect open profit.")
    if rules <= 1:
        weaknesses.append("Only one entry condition — prone to false signals; add a confirmation.")
    if rules >= 5:
        weaknesses.append("Many conditions — may over-fit and trade rarely.")
    if risk_pct > 0.03:
        weaknesses.append(f"Risk per trade is {risk_pct*100:.1f}% — aggressive.")
        improvements.append("Reduce risk per trade to 1–2%.")
    if not spec.get("session"):
        improvements.append("Consider a session filter (e.g. London / New York) to avoid dead hours.")

    # confidence from real simulation, when available
    conf_score, expected = 40, "Needs a backtest to estimate behaviour."
    warnings = []
    if results and results.get("total_trades"):
        n = results["total_trades"]
        pf = results.get("profit_factor", 0) or 0
        wr = results.get("win_rate", 0) or 0
        dd = results.get("max_drawdown_pct", 0) or 0
        warnings = validate(spec, results)
        conf_score = int(max(0, min(100,
            50 + (pf - 1) * 30 + (10 if n >= 50 else -10 if n < 30 else 0) - max(0, dd - 20))))
        expected = (f"~{n} trades, {wr:.0f}% win rate, profit factor {pf:.2f}, "
                    f"max drawdown {dd:.0f}% in simulation.")
        if pf >= 1.3 and n >= 30:
            strengths.append(f"Profitable in simulation (PF {pf:.2f} over {n} trades).")
        elif pf < 1 and n:
            weaknesses.append("Unprofitable in simulation (profit factor below 1).")

    return {
        "complexity": complexity, "rule_count": rules,
        "risk_level": risk_level,
        "expected_behaviour": expected,
        "strengths": strengths or ["Clear, simple logic."],
        "weaknesses": weaknesses or ["No obvious flaws detected."],
        "improvements": improvements or ["Looks solid — validate with paper trading before any live use."],
        "estimated_confidence": conf_score,
        "confidence_level": confidence_level(conf_score),
        "summary": describe(spec),
        "warnings": warnings,
    }
