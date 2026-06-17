"""Custom (user-built) strategies — rule blocks + real-data simulator.

A custom strategy is a JSON spec: entry conditions combined with AND/OR (each rule
optionally NOT-negated), plus stop / take-profit / risk / session / max-trades.
``simulate()`` runs it over REAL historical bars and returns full results (trades
with reasons, metrics, equity curve) — for SIMULATION only, before paper trading.

Supported rule types (only what's actually implemented — no fakes):
  ema_cross   fast EMA above/below slow EMA
  rsi         RSI above/below a threshold
  sma_trend   price above/below SMA(n)  (trend filter)
  macd        MACD line above/below its signal
  breakout    close breaks above/below the prior n-bar high/low (price action)
  volume      volume above/below its n-period average
  atr_filter  ATR% above/below a threshold (volatility filter)
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import atr, ema, rsi

RULE_TYPES = ("ema_cross", "rsi", "sma_trend", "macd", "breakout", "volume", "atr_filter",
              "pullback", "support_bounce", "liquidity_sweep", "fair_value_gap")
WARMUP = 210  # enough history for SMA200 etc.


# ----------------------------------------------------------------- indicators
def _sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else (sum(values) / len(values) if values else 0.0)


def _macd(closes, fast, slow, signal):
    if len(closes) < slow + signal:
        return 0.0, 0.0
    ef, es = ema(closes, fast), ema(closes, slow)
    macd_series = [a - b for a, b in zip(ef, es)]
    sig = ema(macd_series, signal)
    return macd_series[-1], sig[-1]


# ----------------------------------------------------------------- rule eval
def _rule(rule: dict, bars, i: int) -> tuple[bool, str]:
    """Evaluate one rule at bar index i. Returns (passed, human reason)."""
    t = rule.get("type")
    window = bars[:i + 1]
    closes = [b.close for b in window]
    p = rule

    if t == "ema_cross":
        f, s = int(p.get("fast", 20)), int(p.get("slow", 50))
        if len(closes) < s + 1:
            return False, ""
        fv, sv = ema(closes, f)[-1], ema(closes, s)[-1]
        up = fv > sv
        ok = up if p.get("dir", "above") == "above" else (not up)
        return ok, f"EMA{f}{'>' if up else '<'}EMA{s}"

    if t == "rsi":
        per = int(p.get("period", 14)); val = float(p.get("value", 50))
        r = rsi(closes, per)
        ok = r > val if p.get("op", "above") == "above" else r < val
        return ok, f"RSI {r:.0f}{'>' if r > val else '<'}{val:.0f}"

    if t == "sma_trend":
        n = int(p.get("period", 200))
        if len(closes) < n:
            return False, ""
        sv = _sma(closes, n)
        above = closes[-1] > sv
        ok = above if p.get("dir", "above") == "above" else (not above)
        return ok, f"price{'>' if above else '<'}SMA{n}"

    if t == "macd":
        m, sig = _macd(closes, int(p.get("fast", 12)), int(p.get("slow", 26)), int(p.get("signal", 9)))
        above = m > sig
        ok = above if p.get("dir", "above") == "above" else (not above)
        return ok, f"MACD{'>' if above else '<'}signal"

    if t == "breakout":
        lb = int(p.get("lookback", 20))
        if i < lb:
            return False, ""
        up = p.get("dir", "up") == "up"
        prior = bars[i - lb:i]
        if up:
            ok = bars[i].close > max(b.high for b in prior)
            return ok, f"break {lb}-bar high"
        ok = bars[i].close < min(b.low for b in prior)
        return ok, f"break {lb}-bar low"

    if t == "volume":
        n = int(p.get("period", 20))
        if i < n:
            return False, ""
        vols = [b.volume for b in bars[i - n:i]]
        avg = sum(vols) / n if n else 0
        above = bars[i].volume > avg
        ok = above if p.get("op", "above") == "above" else (not above)
        return ok, "vol>avg" if above else "vol<avg"

    if t == "atr_filter":
        per = int(p.get("period", 14)); val = float(p.get("value_pct", 4)) / 100.0
        a = atr(window, per)
        pct = a / closes[-1] if closes and closes[-1] else 0
        below = pct < val
        ok = below if p.get("op", "below") == "below" else (not below)
        return ok, f"ATR {pct*100:.1f}%"

    # ---- price action ----
    if t == "pullback":  # bounce off a moving average in the trend's direction
        n = int(p.get("period", 20))
        if len(closes) < n + 1:
            return False, ""
        ev = ema(closes, n)[-1]
        if p.get("dir", "up") == "up":
            return (closes[-1] > ev and bars[i].low <= ev), f"pullback to EMA{n}"
        return (closes[-1] < ev and bars[i].high >= ev), f"pullback to EMA{n}"

    if t == "support_bounce":  # price reacting at a recent support/resistance level
        lb = int(p.get("lookback", 30)); tol = float(p.get("tolerance_pct", 0.5)) / 100.0
        if i < lb:
            return False, ""
        prior = bars[i - lb:i]
        if p.get("dir", "support") == "support":
            lvl = min(b.low for b in prior)
            return (lvl <= bars[i].close <= lvl * (1 + tol)), f"near {lb}-bar support"
        lvl = max(b.high for b in prior)
        return (lvl * (1 - tol) <= bars[i].close <= lvl), f"near {lb}-bar resistance"

    if t == "liquidity_sweep":  # wick beyond a level then reclaim (stop hunt)
        lb = int(p.get("lookback", 20))
        if i < lb:
            return False, ""
        prior = bars[i - lb:i]
        if p.get("dir", "down") == "down":  # sweep lows, reclaim -> bullish
            lo = min(b.low for b in prior)
            return (bars[i].low < lo and bars[i].close > lo), "swept lows + reclaim"
        hi = max(b.high for b in prior)
        return (bars[i].high > hi and bars[i].close < hi), "swept highs + reject"

    if t == "fair_value_gap":  # 3-candle imbalance
        if i < 2:
            return False, ""
        if p.get("dir", "up") == "up":
            return (bars[i - 2].high < bars[i].low), "bullish FVG"
        return (bars[i - 2].low > bars[i].high), "bearish FVG"

    return False, ""


def evaluate(tree: dict, bars, i: int) -> tuple[bool, list[str]]:
    """Evaluate a condition tree {op: AND|OR, rules: [...]}. A rule may carry
    'negate': true (NOT). Returns (matched, reasons-for-passing-rules)."""
    op = (tree.get("op") or "AND").upper()
    rules = tree.get("rules") or []
    if not rules:
        return False, []
    results, reasons = [], []
    for r in rules:
        passed, why = _rule(r, bars, i)
        if r.get("negate"):
            passed = not passed
            why = f"NOT({why})" if why else why
        results.append(passed)
        if passed and why:
            reasons.append(why)
    matched = all(results) if op == "AND" else any(results)
    return matched, reasons


# ----------------------------------------------------------------- simulator
def _stop_distance(cfg: dict, entry: float, bars, i: int) -> float:
    if (cfg.get("type") or "atr") == "pct":
        return entry * float(cfg.get("pct", 2)) / 100.0
    a = atr(bars[:i + 1], int(cfg.get("period", 14)))
    return float(cfg.get("mult", 1.5)) * a


def _target_distance(cfg: dict, risk_abs: float, entry: float) -> float:
    if (cfg.get("type") or "rr") == "pct":
        return entry * float(cfg.get("pct", 3)) / 100.0
    return float(cfg.get("rr", 1.5)) * risk_abs


def _in_session(ts, session: dict) -> bool:
    start, end = int(session.get("start", 0)), int(session.get("end", 24))
    return start <= ts.hour < end


def simulate(spec: dict, bars, *, fee: float = 0.0004, slippage: float = 0.0002,
             starting_balance: float = 10_000.0) -> dict:
    """Run a custom strategy spec over historical bars. SIMULATION ONLY."""
    side = spec.get("side", "long")
    entry_tree = spec.get("entry") or {"op": "AND", "rules": []}
    stop_cfg = spec.get("stop") or {"type": "atr", "mult": 1.5, "period": 14}
    target_cfg = spec.get("target") or {"type": "rr", "rr": 1.5}
    risk_pct = float(spec.get("risk_per_trade_pct", 0.01))
    max_per_day = int(spec.get("max_trades_per_day", 0) or 0)
    session = spec.get("session")
    cost = fee + slippage

    pos = None
    trades: list[dict] = []
    day_count: dict[str, int] = {}

    for i in range(WARMUP, len(bars)):
        bar = bars[i]
        if pos is not None:
            exit_px = result = None
            if pos["side"] == "long":
                if bar.low <= pos["stop"]:
                    exit_px, result = pos["stop"], "loss"
                elif bar.high >= pos["target"]:
                    exit_px, result = pos["target"], "win"
            else:
                if bar.high >= pos["stop"]:
                    exit_px, result = pos["stop"], "loss"
                elif bar.low <= pos["target"]:
                    exit_px, result = pos["target"], "win"
            if exit_px is not None:
                move = (exit_px - pos["entry"]) if pos["side"] == "long" else (pos["entry"] - exit_px)
                r = move / pos["risk"] - cost * pos["entry"] * 2 / pos["risk"]
                trades.append({
                    "side": pos["side"], "entry": round(pos["entry"], 6), "exit": round(exit_px, 6),
                    "stop": round(pos["stop"], 6), "target": round(pos["target"], 6),
                    "r": round(r, 3), "result": "win" if r > 0 else "loss",
                    "reason": pos["reason"],
                    "entry_time": pos["time"].isoformat(), "exit_time": bar.timestamp.isoformat(),
                })
                pos = None

        if pos is None:
            if session and not _in_session(bar.timestamp, session):
                continue
            day = bar.timestamp.date().isoformat()
            if max_per_day and day_count.get(day, 0) >= max_per_day:
                continue
            matched, reasons = evaluate(entry_tree, bars, i)
            if matched:
                entry_px = bar.close
                risk_abs = _stop_distance(stop_cfg, entry_px, bars, i)
                if risk_abs <= 0:
                    continue
                tgt = _target_distance(target_cfg, risk_abs, entry_px)
                if side == "long":
                    stop, target = entry_px - risk_abs, entry_px + tgt
                else:
                    stop, target = entry_px + risk_abs, entry_px - tgt
                pos = {"side": side, "entry": entry_px, "stop": stop, "target": target,
                       "risk": risk_abs, "reason": "; ".join(reasons) or "entry conditions met",
                       "time": bar.timestamp}
                day_count[day] = day_count.get(day, 0) + 1

    return _results(trades, starting_balance, risk_pct, bars)


def _results(trades: list, start: float, risk_pct: float, bars) -> dict:
    rs = [t["r"] for t in trades]
    n = len(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gp, gl = sum(wins), -sum(losses)
    # equity (R) for drawdown + $ compounding
    eqR = peak = ddR = 0.0
    cw = cl = mcw = mcl = 0
    bal = start
    curve = [{"t": None, "equity": round(start, 2)}]
    for t in trades:
        eqR += t["r"]
        peak = max(peak, eqR)
        ddR = max(ddR, peak - eqR)
        if t["r"] > 0:
            cw += 1; cl = 0; mcw = max(mcw, cw)
        else:
            cl += 1; cw = 0; mcl = max(mcl, cl)
        bal *= (1 + risk_pct * t["r"])
        curve.append({"t": t["exit_time"], "equity": round(bal, 2)})
    # $ max drawdown %
    pe = pp = ddp = 0.0
    eq2 = start
    pp = start
    for c in curve[1:]:
        eq2 = c["equity"]; pp = max(pp, eq2)
        ddp = max(ddp, (pp - eq2) / pp if pp else 0)
    avg_win = (gp / len(wins)) if wins else 0.0
    avg_loss = (gl / len(losses)) if losses else 0.0
    span_days = ((bars[-1].timestamp - bars[WARMUP].timestamp).days) if len(bars) > WARMUP else 0
    return {
        "simulation": True,
        "data_points": len(bars),
        "total_trades": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "wins": len(wins), "losses": len(losses),
        "profit_factor": round(gp / gl, 2) if gl else (gp and 99.0 or 0.0),
        "net_r": round(sum(rs), 2),
        "net_pct": round(sum(rs) * risk_pct * 100, 1),
        "max_drawdown_r": round(ddR, 1),
        "max_drawdown_pct": round(ddp * 100, 1),
        "avg_rr": round(avg_win / avg_loss, 2) if avg_loss else 0.0,
        "avg_win_r": round(avg_win, 2), "avg_loss_r": round(-avg_loss, 2),
        "best_r": round(max(rs), 2) if rs else 0.0,
        "worst_r": round(min(rs), 2) if rs else 0.0,
        "max_consecutive_wins": mcw, "max_consecutive_losses": mcl,
        "end_balance": round(bal, 2),
        "span_days": span_days,
        "equity_curve": curve,
        "trades": trades[-200:],
    }


# ----------------------------------------------------------------- validation
def validate(spec: dict, results: dict) -> list[dict]:
    """Honest, simulation-based warnings (the doc's required checks)."""
    out = []

    def warn(level, msg):
        out.append({"level": level, "message": msg})

    risk = float(spec.get("risk_per_trade_pct", 0.01))
    if risk > 0.03:
        warn("danger", f"Risk per trade is {risk*100:.1f}% — above 3% is aggressive and can blow up the account.")
    n = results.get("total_trades", 0)
    if n < 30:
        warn("warning", f"Only {n} trades in simulation — too few to trust; results are not statistically significant.")
    if results.get("max_drawdown_pct", 0) > 30:
        warn("danger", f"Max drawdown is {results['max_drawdown_pct']:.0f}% — very large; most people can't sit through this.")
    if results.get("win_rate", 0) > 60 and results.get("profit_factor", 0) < 1.1:
        warn("warning", "High win rate but weak profit factor — small wins and big losses; one bad trade erases many.")
    if n < 50 and results.get("profit_factor", 0) > 2.5:
        warn("warning", "Very high profit factor on few trades — likely overfit. Validate on out-of-sample data before trusting it.")
    if results.get("profit_factor", 0) < 1 and n > 0:
        warn("danger", "Strategy is unprofitable in simulation (profit factor below 1).")
    if not out and n >= 30:
        warn("ok", "No major red flags in simulation. Validate further with paper trading before any live use.")
    return out


# ----------------------------------------------------------------- describe
def _phrase_rule(r: dict) -> str:
    t, neg = r.get("type"), r.get("negate")
    s = {
        "ema_cross": f"EMA{r.get('fast',20)} is {r.get('dir','above')} EMA{r.get('slow',50)}",
        "rsi": f"RSI({r.get('period',14)}) is {r.get('op','above')} {r.get('value',50)}",
        "sma_trend": f"price is {r.get('dir','above')} the {r.get('period',200)} SMA",
        "macd": f"MACD is {r.get('dir','above')} its signal line",
        "breakout": f"price breaks the {r.get('lookback',20)}-bar {'high' if r.get('dir','up')=='up' else 'low'}",
        "volume": f"volume is {r.get('op','above')} its {r.get('period',20)}-bar average",
        "atr_filter": f"volatility (ATR) is {r.get('op','below')} {r.get('value_pct',4)}%",
        "pullback": f"price pulls back to the {r.get('period',20)} EMA in the {r.get('dir','up')} direction",
        "support_bounce": f"price reacts at the {r.get('lookback',30)}-bar {r.get('dir','support')}",
        "liquidity_sweep": f"price sweeps the {r.get('lookback',20)}-bar {'lows' if r.get('dir','down')=='down' else 'highs'} and reverses",
        "fair_value_gap": f"a {'bullish' if r.get('dir','up')=='up' else 'bearish'} fair-value gap forms",
    }.get(t, t or "a condition")
    return f"NOT ({s})" if neg else s


def describe(spec: dict) -> str:
    side = spec.get("side", "long")
    entry = spec.get("entry") or {}
    rules = entry.get("rules") or []
    joiner = f" {entry.get('op','AND')} "
    conds = joiner.join(_phrase_rule(r) for r in rules) if rules else "no entry conditions set"
    stop = spec.get("stop") or {"type": "atr", "mult": 1.5}
    target = spec.get("target") or {"type": "rr", "rr": 1.5}
    stop_txt = (f"a {stop.get('mult',1.5)}× ATR stop" if (stop.get('type','atr') == 'atr')
                else f"a {stop.get('pct',2)}% stop")
    tgt_txt = (f"a {target.get('rr',1.5)} risk:reward target" if (target.get('type','rr') == 'rr')
               else f"a {target.get('pct',3)}% target")
    return (f"This strategy enters {side} when {conds}. "
            f"It exits using {stop_txt} and {tgt_txt}, "
            f"risking {float(spec.get('risk_per_trade_pct',0.01))*100:.1f}% of equity per trade.")

