"""Evidence-based strategy review — conclusions computed FROM backtest trades.

Every finding carries the statistic that produced it, so nothing here is an
opinion. Anything the trade record cannot support is reported in
``not_derivable`` rather than guessed — the review says "I can't tell you that
and here's why" instead of inventing a plausible sentence.

Available per trade (strategies.custom.simulate): side, entry, exit, stop,
target, r, result, reason, exit_reason, entry_time, exit_time, bars_held.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from services.strategy_builder import CONFIG

_MIN_SAMPLE = 5     # below this a per-bucket verdict is noise, not evidence


def _sessions() -> list[dict]:
    return [s for s in CONFIG.get("sessions", []) if s.get("key") != "any"]


def _hour(ts: Any) -> Optional[int]:
    if isinstance(ts, datetime):
        return ts.hour
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
        except ValueError:
            return None
    return None


def _bucket_stats(rows: list[dict]) -> dict:
    n = len(rows)
    rs = [float(t.get("r") or 0.0) for t in rows]
    wins = sum(1 for r in rs if r > 0)
    return {"trades": n, "net_r": round(sum(rs), 2),
            "avg_r": round(sum(rs) / n, 3) if n else 0.0,
            "win_rate": round(100 * wins / n, 1) if n else 0.0}


def session_breakdown(trades: list[dict]) -> list[dict]:
    """Net R per named trading session, from each trade's real entry hour."""
    out = []
    for s in _sessions():
        start, end = int(s["start"]), int(s["end"])
        rows = [t for t in trades
                if (h := _hour(t.get("entry_time"))) is not None and start <= h < end]
        if rows:
            out.append({"session": s["label"], **_bucket_stats(rows)})
    return sorted(out, key=lambda d: d["net_r"], reverse=True)


def regime_breakdown(trades: list[dict]) -> list[dict]:
    """Net R per MARKET REGIME, when the quality filter tagged trades with one.

    The TradeBrain records the regime at entry (Trending / Ranging / High
    Volatility / …), so market-condition performance is real evidence — not an
    inference. Returns [] when the filter was off and no trade carries a tag."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        rg = t.get("regime")
        if rg:
            groups[str(rg)].append(t)
    return sorted(({"regime": k, **_bucket_stats(v)} for k, v in groups.items()),
                  key=lambda d: d["net_r"], reverse=True)


def setup_breakdown(trades: list[dict]) -> list[dict]:
    """Net R per setup type tagged by the brain (when available)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        st = t.get("setup_type")
        if st:
            groups[str(st)].append(t)
    return sorted(({"setup_type": k, **_bucket_stats(v)} for k, v in groups.items()),
                  key=lambda d: d["net_r"], reverse=True)


def exit_reason_breakdown(trades: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        groups[str(t.get("exit_reason") or "unknown")].append(t)
    return sorted(({"exit_reason": k, **_bucket_stats(v)} for k, v in groups.items()),
                  key=lambda d: d["trades"], reverse=True)


def _hold_insight(trades: list[dict]) -> Optional[dict]:
    wins = [t for t in trades if float(t.get("r") or 0) > 0]
    losses = [t for t in trades if float(t.get("r") or 0) <= 0]
    if len(wins) < _MIN_SAMPLE or len(losses) < _MIN_SAMPLE:
        return None
    aw = sum(int(t.get("bars_held") or 0) for t in wins) / len(wins)
    al = sum(int(t.get("bars_held") or 0) for t in losses) / len(losses)
    return {"avg_bars_winners": round(aw, 1), "avg_bars_losers": round(al, 1)}


def evidence_review(spec: dict, results: Optional[dict]) -> dict:
    """Build the review. Returns ``available: False`` when there is no backtest
    to reason from — never a review invented from the spec alone."""
    if not results or not results.get("trades"):
        return {"available": False,
                "note": "No completed backtest trades to review. Run a backtest first — "
                        "this review is computed only from real results.",
                "strengths": [], "weaknesses": [], "sessions": [],
                "exit_reasons": [], "risk": None, "not_derivable": []}

    trades = list(results.get("trades") or [])
    n = len(trades)
    strengths: list[dict] = []
    weaknesses: list[dict] = []

    def add(bucket: list[dict], claim: str, stat: str, value: Any):
        bucket.append({"claim": claim, "stat": stat, "value": value})

    pf = results.get("profit_factor")
    exp = results.get("expectancy_r")
    wr = results.get("win_rate")
    dd = results.get("max_drawdown_r")
    net = results.get("net_r")

    if isinstance(pf, (int, float)):
        (add(strengths, "Positive edge across the sample", "profit factor", round(pf, 2))
         if pf >= 1.3 else
         add(weaknesses, "Little or no edge in this sample", "profit factor", round(pf, 2)))
    if isinstance(exp, (int, float)):
        (add(strengths, "Each trade carries a positive expectancy", "expectancy (R/trade)", round(exp, 3))
         if exp > 0 else
         add(weaknesses, "Average trade loses money", "expectancy (R/trade)", round(exp, 3)))
    if isinstance(dd, (int, float)) and isinstance(net, (int, float)) and dd:
        ratio = round(abs(net / dd), 2) if dd else None
        if ratio is not None:
            (add(strengths, "Return is large relative to worst drawdown", "net R / max drawdown R", ratio)
             if ratio >= 2 else
             add(weaknesses, "Drawdown is large relative to the return earned", "net R / max drawdown R", ratio))
    if isinstance(wr, (int, float)) and wr < 35:
        add(weaknesses, "Low hit-rate — needs large winners to stay profitable", "win rate %", round(wr, 1))
    if n < 30:
        add(weaknesses, "Small sample — treat these numbers as provisional", "trades", n)
    else:
        add(strengths, "Sample large enough to be meaningful", "trades", n)

    # direction — straight from the engine's own split
    lnr, snr = results.get("long_net_r"), results.get("short_net_r")
    lt, st = results.get("long_trades") or 0, results.get("short_trades") or 0
    direction = None
    if lt and st:
        better = "long" if (lnr or 0) >= (snr or 0) else "short"
        direction = {"better_side": better, "long_net_r": lnr, "short_net_r": snr,
                     "long_trades": lt, "short_trades": st}

    sessions = session_breakdown(trades)
    best_session = next((s for s in sessions if s["trades"] >= _MIN_SAMPLE), None)
    if best_session:
        add(strengths, f"Strongest during {best_session['session']}",
            "net R in that session", best_session["net_r"])

    exits = exit_reason_breakdown(trades)
    losing = [e for e in exits if e["avg_r"] < 0]
    common_loss = max(losing, key=lambda e: e["trades"]) if losing else None
    if common_loss and common_loss["trades"] >= _MIN_SAMPLE:
        add(weaknesses, f"Most losses come from: {common_loss['exit_reason']}",
            "losing trades with that exit", common_loss["trades"])

    hold = _hold_insight(trades)
    if hold:
        if hold["avg_bars_losers"] > hold["avg_bars_winners"]:
            add(weaknesses, "Losers are held longer than winners",
                "avg bars (losers vs winners)",
                f"{hold['avg_bars_losers']} vs {hold['avg_bars_winners']}")
        else:
            add(strengths, "Winners are given more room than losers",
                "avg bars (winners vs losers)",
                f"{hold['avg_bars_winners']} vs {hold['avg_bars_losers']}")

    risk = {"max_drawdown_r": dd, "max_drawdown_pct": results.get("max_drawdown_pct"),
            "max_consecutive_losses": results.get("max_consecutive_losses"),
            "risk_per_trade_pct": spec.get("risk_per_trade_pct"),
            "worst_trade_r": results.get("worst_r")}

    # market conditions — real evidence when the quality filter tagged regimes
    regimes = regime_breakdown(trades)
    best_regime = next((r for r in regimes if r["trades"] >= _MIN_SAMPLE), None)
    worst_regime = next((r for r in reversed(regimes) if r["trades"] >= _MIN_SAMPLE), None)
    if best_regime:
        add(strengths, f"Performs best in {best_regime['regime']} conditions",
            "net R in that regime", best_regime["net_r"])
    if worst_regime and worst_regime is not best_regime and worst_regime["net_r"] < 0:
        add(weaknesses, f"Loses money in {worst_regime['regime']} conditions",
            "net R in that regime", worst_regime["net_r"])
    setups = setup_breakdown(trades)

    # What this data honestly cannot answer — stated, not invented.
    not_derivable = []
    if not regimes:
        not_derivable.append({
            "question": "Best / worst market conditions (trending, ranging, volatile)",
            "why": "These trades carry no regime tag, which happens when the quality "
                   "filter is switched off. Re-run with quality_filter enabled to get "
                   "a regime breakdown."})
    not_derivable.append({
        "question": "Most profitable asset",
        "why": "A strategy runs on a single symbol, so one backtest cannot rank "
               "assets. Run the same strategy on other symbols to compare."})

    return {"available": True, "trades_reviewed": n,
            "strengths": strengths, "weaknesses": weaknesses,
            "sessions": sessions, "best_session": best_session,
            "regimes": regimes, "best_regime": best_regime, "worst_regime": worst_regime,
            "setups": setups,
            "exit_reasons": exits, "most_common_loss": common_loss,
            "direction": direction, "hold_times": hold, "risk": risk,
            "not_derivable": not_derivable}


# --------------------------------------------------------------- date ranges
# Backtest range presets -> bar counts, derived from the real timeframe so the
# window means what it says (rather than a fixed bar count that silently means
# a different span per timeframe).

_TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
               "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
               "1d": 1440, "1w": 10080}
RANGES = {"3M": 90, "6M": 182, "1Y": 365, "3Y": 1095, "5Y": 1825}


def bars_for_range(timeframe: str, key: str, cap: int = 10000) -> int:
    """How many candles cover ``key`` on ``timeframe`` (clamped to the engine's
    limit). Returns the cap when the request exceeds available history."""
    mins = _TF_MINUTES.get(str(timeframe).lower(), 240)
    days = RANGES.get(str(key).upper())
    if not days:
        return min(3000, cap)
    return max(300, min(int(days * 24 * 60 / mins), cap))
