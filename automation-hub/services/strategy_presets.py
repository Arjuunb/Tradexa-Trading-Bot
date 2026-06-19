"""Strategy presets + the control-center simulation/compare logic.

Maps the human strategy names shown in the top control bar to runnable specs,
applies the brain-tuning panel settings, and reruns REAL simulations so the user
can quickly switch strategy / symbol / timeframe / brain settings and see how
performance changes. Rule-based presets run through the brain-aware custom
simulator (full diagnosis + blocked log + quality score); class-based presets
run through the built-in strategy simulator with the same quality gate.
"""
from __future__ import annotations

from typing import Optional

# The strategy options the control bar offers.
PRESETS: dict = {
    "Decision Brain": {"kind": "builtin", "key": "brain"},
    "Trend Following": {"kind": "builtin", "key": "supertrend"},
    "Supply/Demand": {"kind": "builtin", "key": "smc"},
    "Breakout Retest": {"kind": "custom", "side": "long",
                        "rules": [{"type": "breakout", "lookback": 20, "dir": "up"},
                                  {"type": "pullback", "period": 20, "dir": "up"}]},
    "Support/Resistance Rejection": {"kind": "custom", "side": "long",
                                     "rules": [{"type": "support_bounce", "lookback": 30,
                                                "dir": "support", "tolerance_pct": 0.5}]},
    "EMA 8/30": {"kind": "custom", "side": "long",
                 "rules": [{"type": "ema_cross", "fast": 8, "slow": 30, "dir": "above"}]},
    "Liquidity Sweep": {"kind": "custom", "side": "long",
                        "rules": [{"type": "liquidity_sweep", "lookback": 20, "dir": "down"},
                                  {"type": "choch", "dir": "up"}]},
    "Custom Strategy": {"kind": "custom_user"},
}
STRATEGY_OPTIONS = list(PRESETS)
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d", "1w"]
MODES = ["Simulation", "Paper Trading", "Live Trading (locked)"]

# default brain-tuning panel
DEFAULT_TUNING = {
    "min_score": 60, "rr": 2.0,
    "trend_filter": True, "volume_filter": False, "regime_filter": True,
    "session_filter": False, "max_trades_per_day": 0, "cooldown_after_loss": 0,
}


def _apply_tuning(spec: dict, tuning: dict) -> dict:
    """Translate the brain-tuning panel into concrete spec settings."""
    t = {**DEFAULT_TUNING, **(tuning or {})}
    spec["min_score"] = int(t["min_score"])
    spec["target"] = {"type": "rr", "rr": float(t["rr"])}
    # trend + regime live inside the brain quality filter
    spec["quality_filter"] = bool(t["trend_filter"] or t["regime_filter"])
    rules = list((spec.get("entry") or {}).get("rules") or [])
    if t["volume_filter"] and not any(r.get("type") == "volume" for r in rules):
        rules.append({"type": "volume", "period": 20, "op": "above"})
    spec.setdefault("entry", {"op": "AND"})["rules"] = rules
    if t["session_filter"]:
        spec["session"] = {"start": 7, "end": 21}      # London+NY window (UTC)
    else:
        spec.pop("session", None)
    spec["max_trades_per_day"] = int(t["max_trades_per_day"])
    spec["cooldown_after_loss"] = int(t["cooldown_after_loss"])   # recorded; used live
    return spec


def resolve(strategy: str, symbol: str, timeframe: str, tuning: dict,
            custom_spec: Optional[dict] = None) -> dict:
    """Return a runnable descriptor: {kind, key|spec, label}."""
    preset = PRESETS.get(strategy)
    if preset is None:
        return {"error": f"unknown strategy {strategy}"}
    if preset["kind"] == "builtin":
        return {"kind": "builtin", "key": preset["key"], "label": strategy}
    if preset["kind"] == "custom_user":
        if not custom_spec:
            return {"error": "Custom Strategy selected but no custom spec provided."}
        spec = {**custom_spec, "symbol": symbol, "timeframe": timeframe,
                "name": custom_spec.get("name", "Custom")}
    else:
        spec = {"name": strategy, "symbol": symbol, "timeframe": timeframe,
                "side": preset.get("side", "long"),
                "entry": {"op": "AND", "rules": [dict(r) for r in preset["rules"]]},
                "stop": {"type": "atr", "mult": 1.5, "period": 14},
                "risk_per_trade_pct": 0.01, "mtf_filter": True}
    return {"kind": "custom", "spec": _apply_tuning(spec, tuning), "label": strategy}


def run_simulation(strategy: str, symbol: str, timeframe: str, *, tuning: dict = None,
                   custom_spec: dict = None, bars: int = 4000) -> dict:
    """Run a REAL simulation for the chosen control-bar configuration."""
    from data.market_data import get_bars
    from strategies.custom import simulate, simulate_strategy
    from strategies.brain import TradeBrain
    from strategies.diagnosis import diagnose

    desc = resolve(strategy, symbol, timeframe, tuning or {}, custom_spec)
    if "error" in desc:
        return desc

    rows, source = get_bars(symbol, n=max(600, min(int(bars), 10000)), timeframe=timeframe)
    if not rows:
        return {"error": "Historical data not available. Please load Binance data first "
                         "(run /data/sync).", "data_source": source, "available": False}

    min_score = int((tuning or {}).get("min_score", DEFAULT_TUNING["min_score"]))
    brain = TradeBrain()
    if desc["kind"] == "builtin":
        from webhook_api import _build_builtin   # reuse the builder
        strat = _build_builtin(desc["key"], symbol)
        results = simulate_strategy(strat, rows, brain=brain, min_score=min_score)
    else:
        spec = desc["spec"]
        use_brain = spec.get("quality_filter", True)
        results = simulate(spec, rows, brain=brain if use_brain else None,
                           min_score=min_score if use_brain else 0)
    results["diagnosis"] = diagnose(results, results.get("blocked"))
    warning = underperforming(results)
    return {
        "strategy": strategy, "symbol": symbol, "timeframe": timeframe,
        "data_source": source, "available": True, "results": results,
        "warning": warning, "spec": desc.get("spec"),
    }


def underperforming(results: dict) -> Optional[dict]:
    """Return a warning when a strategy is losing / weak / too drawdown-heavy."""
    n = results.get("total_trades", 0)
    if n < 10:
        return None                       # not enough trades to judge
    pf = results.get("profit_factor", 0)
    wr = results.get("win_rate", 0)
    dd = results.get("max_drawdown_pct", 0)
    reasons = []
    if pf < 1.0:
        reasons.append(f"profit factor {pf} (< 1.0)")
    if wr < 40:
        reasons.append(f"win rate {wr}% (low)")
    if dd > 30:
        reasons.append(f"max drawdown {dd}% (high)")
    if not reasons:
        return None
    return {"level": "warning",
            "message": ("This strategy is underperforming (" + ", ".join(reasons) + "). "
                        "Test another strategy, timeframe, or adjust the brain filters.")}


def compare(a: dict, b: dict, *, bars: int = 4000) -> dict:
    """Compare two control configurations on real data and pick a winner."""
    ra = run_simulation(a["strategy"], a["symbol"], a["timeframe"],
                        tuning=a.get("tuning"), custom_spec=a.get("custom_spec"), bars=bars)
    rb = run_simulation(b["strategy"], b["symbol"], b["timeframe"],
                        tuning=b.get("tuning"), custom_spec=b.get("custom_spec"), bars=bars)
    if not ra.get("available") or not rb.get("available"):
        return {"error": "Historical data not available for one or both configurations.",
                "a": ra, "b": rb}

    def score(r):
        s = r["results"]
        return (s.get("net_r", -1e9), s.get("profit_factor", 0))
    winner = "A" if score(ra) >= score(rb) else "B"
    return {"a": ra, "b": rb, "winner": winner,
            "summary": f"{(ra if winner == 'A' else rb)['strategy']} "
                       f"({(ra if winner == 'A' else rb)['timeframe']}) wins on net R."}
