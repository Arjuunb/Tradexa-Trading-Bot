"""Multi-strategy allocation — put capital where the evidence is.

Two professional moves, both grounded in the bot's own records:

  adaptive_choice   pick each symbol's STRATEGY from the market-memory
                    snapshots (which strategy actually earned on this symbol),
                    falling back to the Decision Brain when memory has no
                    sample. Enabled with HUB_AUTO_STRATEGY=adaptive.
  risk_weights      tilt SIZE toward symbols with a proven recent live record.
                    Only ever tilts UP (max 1.25x) on positive evidence — the
                    learning book already handles the penalty side (0.5x on
                    bleeding symbols), so no double-punishment.

Pure functions; the pipeline and engine consume them through small hooks.
"""
from __future__ import annotations

MAX_TILT = 1.25
MIN_TRADES = 8


def risk_weights(history: list[dict], symbols: list[str], lookback: int = 30) -> dict:
    """Per-symbol size multiplier in [1.0, MAX_TILT] from recent closed trades
    (history is newest-first, as the paper engine returns it)."""
    out = {s.upper(): 1.0 for s in symbols}
    by_sym: dict[str, list[float]] = {}
    for t in history:
        if t.get("status", "closed") != "closed" or t.get("rr") is None:
            continue
        sym = (t.get("symbol") or "").upper()
        rs = by_sym.setdefault(sym, [])
        if len(rs) < lookback:
            rs.append(float(t["rr"]))
    for sym in out:
        rs = by_sym.get(sym, [])
        if len(rs) < MIN_TRADES:
            continue                                    # no evidence, no tilt
        expectancy = sum(rs) / len(rs)
        if expectancy >= 0.3:
            out[sym] = MAX_TILT
        elif expectancy > 0.1:
            out[sym] = 1.1
    return out


def allocation_report(history: list[dict], symbols: list[str],
                      memory_store=None) -> dict:
    """What the allocator would do right now, with the evidence shown."""
    weights = risk_weights(history, symbols)
    per_symbol = {}
    by_sym: dict[str, list[float]] = {}
    for t in history:
        if t.get("status", "closed") == "closed" and t.get("rr") is not None:
            by_sym.setdefault((t.get("symbol") or "").upper(), []).append(float(t["rr"]))
    rec = memory_store.recommendations() if memory_store is not None else {}
    best_by_symbol = rec.get("best_strategy_by_symbol", {})
    for s in symbols:
        sym = s.upper()
        rs = by_sym.get(sym, [])[:30]
        per_symbol[sym] = {
            "risk_weight": weights.get(sym, 1.0),
            "recent_trades": len(rs),
            "recent_expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
            "memory_pick": best_by_symbol.get(sym, {}).get("strategy"),
        }
    return {"weights": weights, "per_symbol": per_symbol,
            "note": ("Tilt is evidence-only: 1.0 without 8+ recent trades; up to "
                     f"{MAX_TILT}x on a strong record. The learning book handles the "
                     "penalty side separately.")}


def adaptive_choice(memory_store, symbol: str, default: str = "Decision Brain") -> str:
    """The strategy NAME memory recommends for this symbol (>=3 trades, best
    net R), or the default when memory has no sample for it."""
    try:
        rec = memory_store.recommendations().get("best_strategy_by_symbol", {})
        pick = rec.get(symbol.upper(), {})
        if pick.get("strategy") and pick.get("net_r", 0) > 0:
            return pick["strategy"]
    except Exception:  # noqa: BLE001 — a broken memory file must not stop trading
        pass
    return default


def adaptive_factory(memory_store, timeframe: str = "4h"):
    """Engine strategy factory: per-symbol strategy chosen from memory.
    Falls back to the Decision Brain when memory is empty or the preset
    can't be built."""
    def factory(symbol: str):
        from services.strategy_presets import make_replay_strategy
        name = adaptive_choice(memory_store, symbol)
        strat, err, _sid = make_replay_strategy(name, symbol, timeframe)
        if strat is None or err:
            from strategies.brain_strategy import DecisionBrain
            return DecisionBrain(symbol)
        strat.label = f"Adaptive: {name}"
        return strat
    return factory
