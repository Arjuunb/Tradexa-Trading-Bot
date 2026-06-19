"""Strategy Replay engine — precomputes a no-lookahead decision timeline so the
UI can replay historical market data candle-by-candle, TradingView style.

Everything here is CAUSAL: frame ``i`` is derived only from bars ``[:i+1]``. The
engine never reads a future candle. Higher timeframes are built by resampling
the execution series upward (so every timeframe shares one aligned clock), and
each higher-timeframe trend at execution-bar ``i`` uses only candles that have
already CLOSED by that bar.

Output (one JSON blob the frontend plays back):
    meta      symbol / timeframe / data source / date range / counts
    candles   OHLCV for the execution timeframe (the chart)
    overlays  ema20, ema50, vwap (causal)
    markers   sweeps / BOS / CHoCH / FVG (chart annotations, with bar index)
    zones     order blocks (supply/demand) + swing S/R levels
    frames    per-bar brain state: regime, multi-TF trends, trigger, quality
              score + breakdown, blocked reason
    events    decision-timeline entries (bar index + plain-English reasoning)
    trades    entries/exits with reasons, RR, result and loss analysis
    stats     win rate, profit factor, net R, drawdown, expectancy, long/short …
"""
from __future__ import annotations

from typing import Optional

from bot.data.indicators import atr, ema
from bot.types import SignalType
from services.regime import RegimeDetector
from strategies.smc_strategy import SMCStrategy

# Execution timeframe -> how many execution bars make one higher-tf candle.
TF_FACTORS = {
    "5m": {"15m": 3, "4h": 48, "1d": 288, "1w": 2016},
    "15m": {"4h": 16, "1d": 96, "1w": 672},
}
HTF_ORDER = ["1w", "1d", "4h", "15m"]
HTF_LABEL = {"1w": "Weekly", "1d": "Daily", "4h": "4H", "15m": "15M"}
SCORE_THRESHOLD = 60
MIN_HTF_CANDLES = 10  # higher-tf trend needs at least this many candles to be meaningful
PARTIAL_FRAC = 0.5    # portion booked at the first target
TP1_R = 1.0           # first (partial) target, in R
PARTIAL_MIN_RR = 1.5  # only scale out when the final target is at least this many R


def _resampled_closes(bars, factor):
    """Closed higher-tf candle closes, aligned to the start of the series.
    Candle k spans exec bars [k*factor:(k+1)*factor]; only complete candles."""
    closes = []
    n = len(bars)
    k = 0
    while (k + 1) * factor <= n:
        closes.append(bars[(k + 1) * factor - 1].close)
        k += 1
    return closes


def _trend_series(closes, fast=5, slow=12):
    """Per-candle trend code: 1 bullish, -1 bearish, 0 neutral. Causal EMA."""
    if len(closes) < slow:
        return [0] * len(closes)
    ef, es = ema(closes, fast), ema(closes, slow)
    return [1 if ef[i] > es[i] else -1 if ef[i] < es[i] else 0 for i in range(len(closes))]


def _trend_code_to_str(code) -> str:
    return {1: "Bullish", -1: "Bearish", 0: "Neutral"}.get(code, "n/a")


def _vwap_series(bars):
    """Rolling VWAP that resets each UTC day. Causal."""
    out = []
    cum_pv = cum_v = 0.0
    cur_day = None
    for b in bars:
        day = b.timestamp.date()
        if day != cur_day:
            cum_pv = cum_v = 0.0
            cur_day = day
        tp = (b.high + b.low + b.close) / 3.0
        cum_pv += tp * (b.volume or 0.0)
        cum_v += (b.volume or 0.0)
        out.append(round(cum_pv / cum_v, 6) if cum_v > 0 else round(b.close, 6))
    return out


def _in_killzone(hour: int) -> bool:
    # London + New York overlap window (UTC). Soft factor for 24/7 crypto.
    return 7 <= hour < 21


def _score(side: int, trends: dict, vol_ratio: float, sweep: bool, struct: bool,
           fvg: bool, rr: float, hour: int, regime: str, near_resistance: bool):
    """Trade-quality score 0..100 with a transparent breakdown."""
    want = "Bullish" if side > 0 else "Bearish"
    agree = sum(1 for v in trends.values() if v == want)
    total_tf = sum(1 for v in trends.values() if v in ("Bullish", "Bearish")) or 1
    comp = {}
    comp["Trend Alignment"] = round(25 * agree / max(total_tf, 1))
    comp["Volume Confirmation"] = 15 if vol_ratio >= 1.2 else round(15 * min(1.0, vol_ratio / 1.2) * 0.8)
    comp["Structure Confirmation"] = round(20 * (int(sweep) + int(struct) + int(fvg)) / 3)
    comp["Risk Reward"] = 15 if rr >= 2 else (round(15 * min(1.0, rr / 2)) if rr else 0)
    comp["Session Quality"] = 10 if _in_killzone(hour) else 5
    comp["Volatility Condition"] = (15 if regime in ("Trending", "High Volatility")
                                    else 8 if regime == "Ranging" else 3)
    if near_resistance:
        comp["Risk Reward"] = max(0, comp["Risk Reward"] - 8)
    return int(sum(comp.values())), comp


def _block_reason(comp: dict, near_resistance: bool) -> str:
    if near_resistance:
        return "Near Resistance"
    worst = min(comp, key=lambda k: comp[k])
    return {
        "Trend Alignment": "Trend Misalignment",
        "Volume Confirmation": "Weak Volume",
        "Structure Confirmation": "Weak Structure",
        "Risk Reward": "Poor Risk Reward",
        "Session Quality": "Off-session",
        "Volatility Condition": "Choppy Market",
    }.get(worst, "Low Quality Setup")


_TF_SECONDS = {"5m": 300, "15m": 900, "4h": 14400, "1d": 86400, "1w": 604800}


def _parse_date(s):
    if not s:
        return None
    from datetime import datetime, timezone
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def build_replay(symbol: str, exec_tf: str = "15m", limit: int = 800,
                 start=None, end=None) -> dict:
    from data.market_data import get_bars
    if exec_tf not in TF_FACTORS:
        exec_tf = "15m"
    n = max(300, min(int(limit or 800), 1500))
    start_dt, end_dt = _parse_date(start), _parse_date(end)

    # When a start date is given, fetch live candles from ~1200 bars earlier so
    # the higher timeframes have history to form (ignored by non-live sources).
    since_ms = None
    if start_dt is not None:
        since_ms = int((start_dt.timestamp() - _TF_SECONDS[exec_tf] * 1200) * 1000)
    bars, source = get_bars(symbol, n=n + 1200, timeframe=exec_tf, since_ms=since_ms)

    if start_dt is not None or end_dt is not None:
        sel = [k for k, b in enumerate(bars)
               if (start_dt is None or b.timestamp >= start_dt)
               and (end_dt is None or b.timestamp <= end_dt)]
        if sel:
            first, last = sel[0], min(sel[-1], sel[0] + n - 1)  # cap window length
            warm, view = bars[:first], bars[first:last + 1]
        else:
            warm, view = bars, []
    elif len(bars) > n:
        warm, view = bars[:len(bars) - n], bars[len(bars) - n:]
    else:
        warm, view = [], bars

    bars = warm + view          # drop any post-window candles → zero lookahead
    offset = len(warm)          # view[0] is global bar `offset`

    if not view:
        return {"meta": {"symbol": symbol, "timeframe": exec_tf, "data_source": source,
                         "bars": 0, "start": None, "end": None, "htf_available": {},
                         "note": "No data in the selected date range."},
                "candles": [], "overlays": {"ema20": [], "ema50": [], "vwap": []},
                "markers": [], "zones": [], "frames": [], "events": [], "trades": [],
                "stats": _stats([], symbol)}

    # --- precompute higher-timeframe trend series (causal) ---
    factors = TF_FACTORS[exec_tf]
    htf_trends = {}
    for label, f in factors.items():
        closes = _resampled_closes(bars, f)
        htf_trends[label] = (_trend_series(closes), f, len(closes))

    def trends_at(global_i: int) -> dict:
        out = {}
        for label, (series, f, _count) in htf_trends.items():
            closed = ((global_i + 1) // f) - 1   # last CLOSED htf candle index
            if closed < MIN_HTF_CANDLES or closed >= len(series):
                out[HTF_LABEL[label]] = "n/a" if closed < MIN_HTF_CANDLES else _trend_code_to_str(series[-1])
            else:
                out[HTF_LABEL[label]] = _trend_code_to_str(series[closed])
        return out

    # --- overlays on the view ---
    closes_view = [b.close for b in view]
    ema20 = [round(x, 6) for x in ema(closes_view, 20)] if closes_view else []
    ema50 = [round(x, 6) for x in ema(closes_view, 50)] if closes_view else []
    vwap = _vwap_series(view)

    detector = RegimeDetector()
    strat = SMCStrategy(symbol)
    # warm the strategy on the pre-view bars WITHOUT recording (no trading history)
    for b in warm:
        strat.on_bar(b)

    candles, frames, events, markers, trades, zones = [], [], [], [], [], []
    pos = None
    trade_id = 0
    prev_trends = {}
    prev_regime = None
    last_down = last_up = None  # most recent bearish / bullish candle (for order blocks)

    for li, bar in enumerate(view):
        gi = offset + li  # global index into `bars`
        sig = strat.on_bar(bar)
        candles.append({"t": bar.timestamp.isoformat(), "o": round(bar.open, 6), "h": round(bar.high, 6),
                        "l": round(bar.low, 6), "c": round(bar.close, 6), "v": round(bar.volume or 0.0, 2)})

        # --- structure events from the strategy's own causal state ---
        sweep = struct = fvg = False
        if strat._last_sweep_low == gi:
            sweep = True
            markers.append({"idx": li, "price": round(bar.low, 6), "type": "Sweep", "side": "bull"})
            events.append({"idx": li, "kind": "sweep", "text": "Liquidity sweep of lows — stops taken, price reclaimed."})
        if strat._last_sweep_high == gi:
            sweep = True
            markers.append({"idx": li, "price": round(bar.high, 6), "type": "Sweep", "side": "bear"})
            events.append({"idx": li, "kind": "sweep", "text": "Liquidity sweep of highs — stops taken, price rejected."})
        if strat._last_bull_struct == gi:
            struct = True
            markers.append({"idx": li, "price": round(bar.close, 6), "type": "BOS/CHoCH", "side": "bull"})
            events.append({"idx": li, "kind": "structure", "text": "Bullish break of structure (BOS/CHoCH)."})
            if last_down is not None:  # demand order block = last down candle before the impulse
                ob = last_down[1]
                zones.append({"type": "demand", "left_idx": last_down[0],
                              "top": round(max(ob.open, ob.close), 6), "bottom": round(ob.low, 6)})
        if strat._last_bear_struct == gi:
            struct = True
            markers.append({"idx": li, "price": round(bar.close, 6), "type": "BOS/CHoCH", "side": "bear"})
            events.append({"idx": li, "kind": "structure", "text": "Bearish break of structure (BOS/CHoCH)."})
            if last_up is not None:  # supply order block = last up candle before the impulse
                ob = last_up[1]
                zones.append({"type": "supply", "left_idx": last_up[0],
                              "top": round(ob.high, 6), "bottom": round(min(ob.open, ob.close), 6)})
        if bar.close < bar.open:
            last_down = (li, bar)
        elif bar.close > bar.open:
            last_up = (li, bar)
        if strat._last_bull_fvg == gi:
            fvg = True
            markers.append({"idx": li, "price": round(bar.close, 6), "type": "FVG", "side": "bull"})
            events.append({"idx": li, "kind": "fvg", "text": "Bullish fair-value gap (imbalance) formed."})
        if strat._last_bear_fvg == gi:
            fvg = True
            markers.append({"idx": li, "price": round(bar.close, 6), "type": "FVG", "side": "bear"})

        # recency windows (match the SMC strategy)
        p = strat.params
        recent_sweep = min(gi - strat._last_sweep_low, gi - strat._last_sweep_high) <= p["sweep_lookback"]
        recent_struct = min(gi - strat._last_bull_struct, gi - strat._last_bear_struct) <= p["choch_lookback"]
        recent_fvg = min(gi - strat._last_bull_fvg, gi - strat._last_bear_fvg) <= p["fvg_lookback"]

        trends = trends_at(gi)
        regime = detector.detect(bars[:gi + 1]).name

        # decision-timeline: trend flips + regime changes
        for tf_name, val in trends.items():
            if prev_trends.get(tf_name) not in (None, val) and val in ("Bullish", "Bearish"):
                events.append({"idx": li, "kind": "trend", "text": f"{tf_name} trend now {val.lower()}."})
        if regime != prev_regime and prev_regime is not None:
            events.append({"idx": li, "kind": "regime", "text": f"Market regime: {regime}."})
        prev_trends, prev_regime = trends, regime

        # volume confirmation
        vol_ratio = 1.0
        if li >= 20:
            avg = sum(view[j].volume or 0 for j in range(li - 20, li)) / 20
            vol_ratio = (bar.volume / avg) if avg > 0 else 1.0

        # ---------------- manage an open trade (multi-stage exits) ----------------
        if pos is not None:
            s = pos["side"]
            hit_sl = (bar.low <= pos["sl"]) if s == "long" else (bar.high >= pos["sl"])
            if pos["stage"] == 0:
                hit_tp1 = (bar.high >= pos["tp1"]) if s == "long" else (bar.low <= pos["tp1"])
                if hit_sl:  # full stop before any partial -> -1R
                    _close_trade(trades, pos, li, pos["sl"], "Stop loss hit", -1.0, trends, regime, events)
                    pos = None
                elif hit_tp1 and pos["partial"]:  # book a partial, move stop to break-even
                    pos["booked"] = PARTIAL_FRAC * TP1_R
                    pos["stage"] = 1
                    pos["sl"] = pos["entry"]
                    pos["tp1_idx"] = li
                    tr = trades[pos["trade_ref"]]
                    tr["tp1_idx"] = li
                    tr["status"] = "Partial TP / BE"
                    markers.append({"idx": li, "price": round(pos["tp1"], 6), "type": "TP1",
                                    "side": "bull" if s == "long" else "bear"})
                    events.append({"idx": li, "kind": "partial",
                                   "text": f"Partial take-profit (+{TP1_R:g}R) — {int(PARTIAL_FRAC*100)}% "
                                           f"booked, stop moved to break-even."})
                elif hit_tp1 and not pos["partial"]:  # single-target trade
                    r = (pos["tp1"] - pos["entry"]) / pos["risk"] if s == "long" else (pos["entry"] - pos["tp1"]) / pos["risk"]
                    _close_trade(trades, pos, li, pos["tp1"], "Take profit reached", r, trends, regime, events)
                    pos = None
            elif pos["stage"] == 1:  # runner: break-even stop or final target
                hit_tp2 = (bar.high >= pos["tp2"]) if s == "long" else (bar.low <= pos["tp2"])
                if hit_sl:  # break-even stop on the remainder
                    total = pos["booked"] + (1 - PARTIAL_FRAC) * 0.0
                    _close_trade(trades, pos, li, pos["entry"], "Break-even stop after partial", total, trends, regime, events)
                    pos = None
                elif hit_tp2:
                    r2 = (pos["tp2"] - pos["entry"]) / pos["risk"] if s == "long" else (pos["entry"] - pos["tp2"]) / pos["risk"]
                    total = pos["booked"] + (1 - PARTIAL_FRAC) * r2
                    _close_trade(trades, pos, li, pos["tp2"], "Final take-profit reached", total, trends, regime, events)
                    pos = None

        # ---------------- score / trigger / entry ----------------
        side = 0
        if sig is not None:
            side = 1 if sig.type == SignalType.LONG else -1
        # near-resistance check for longs (room to the recent swing high)
        near_res = False
        if side > 0 and strat._swing_high is not None:
            rr_room = (strat._swing_high - bar.close)
            near_res = 0 < rr_room < (atr(bars[:gi + 1], 14) or 1e9)

        breakdown = None
        score = 0
        trigger = "Waiting"
        blocked = False
        block_reason = ""
        if recent_sweep or recent_struct or recent_fvg:
            trigger = "Setup Found"
        if side != 0 and sig is not None:
            rr = abs(sig.take_profit - sig.entry) / max(abs(sig.entry - sig.stop_loss), 1e-9)
            score, breakdown = _score(side, trends, vol_ratio, recent_sweep, recent_struct,
                                      recent_fvg, rr, bar.timestamp.hour, regime, near_res)
            if score >= SCORE_THRESHOLD and pos is None:
                trigger = "Entry Confirmed"
                trade_id += 1
                entry_reasons = _entry_reasons(side, trends, recent_sweep, recent_struct, recent_fvg)
                risk = abs(sig.entry - sig.stop_loss)
                tp2 = sig.take_profit
                final_rr = abs(tp2 - sig.entry) / risk if risk > 0 else 0.0
                partial = final_rr >= PARTIAL_MIN_RR
                tp1 = (sig.entry + TP1_R * risk) if side > 0 else (sig.entry - TP1_R * risk)
                trades.append({
                    "id": trade_id, "symbol": symbol, "side": "long" if side > 0 else "short",
                    "entry_idx": li, "entry": round(sig.entry, 6), "sl": round(sig.stop_loss, 6),
                    "tp": round(tp2, 6), "tp1": round(tp1, 6) if partial else None, "tp1_idx": None,
                    "score": score, "breakdown": breakdown, "entry_reasons": entry_reasons,
                    "exit_idx": None, "exit": None, "exit_reason": None, "result": "Open",
                    "status": "Open", "partial": partial, "rr": None, "loss_analysis": None,
                    "regime": regime, "entry_time": bar.timestamp.isoformat(), "bars_held": None,
                })
                pos = {"side": "long" if side > 0 else "short", "entry": sig.entry, "sl": sig.stop_loss,
                       "tp1": tp1 if partial else tp2, "tp2": tp2, "risk": risk, "partial": partial,
                       "stage": 0, "booked": 0.0, "tp1_idx": None,
                       "trade_ref": len(trades) - 1, "entry_idx": li, "regime": regime}
                events.append({"idx": li, "kind": "entry",
                               "text": f"{pos['side'].title()} opened — score {score}/100, "
                                       f"{', '.join(entry_reasons[:2])}."})
                markers.append({"idx": li, "price": round(sig.entry, 6),
                                "type": "Entry", "side": "bull" if side > 0 else "bear"})
            elif pos is None:
                blocked = True
                block_reason = _block_reason(breakdown, near_res)
                events.append({"idx": li, "kind": "blocked",
                               "text": f"Trade blocked — {block_reason} (score {score}/100)."})

        frames.append({
            "regime": regime, "trends": trends, "trigger": trigger,
            "score": score, "breakdown": breakdown, "blocked": blocked, "reason": block_reason,
            "vol_ratio": round(vol_ratio, 2),
        })

    # keep the most recent supply/demand zones + current swing S/R levels
    zones = zones[-8:] + _zones_from_strategy(strat, offset, len(view))
    stats = _stats(trades, symbol)
    return {
        "meta": {"symbol": symbol, "timeframe": exec_tf, "data_source": source,
                 "bars": len(view), "start": view[0].timestamp.isoformat() if view else None,
                 "end": view[-1].timestamp.isoformat() if view else None,
                 "htf_available": {HTF_LABEL[k]: (v[2] >= MIN_HTF_CANDLES) for k, v in htf_trends.items()}},
        "candles": candles, "overlays": {"ema20": ema20, "ema50": ema50, "vwap": vwap},
        "markers": markers, "zones": zones, "frames": frames, "events": events,
        "trades": trades, "stats": stats,
    }


def _entry_reasons(side, trends, sweep, struct, fvg) -> list:
    out = []
    for name, val in trends.items():
        want = "Bullish" if side > 0 else "Bearish"
        if val == want:
            out.append(f"{name} {val.lower()}")
    if sweep:
        out.append("liquidity sweep")
    if struct:
        out.append("structure shift (BOS/CHoCH)")
    if fvg:
        out.append("fair-value gap")
    return out or ["confluence met"]


def _close_trade(trades, pos, li, exit_px, reason, total_r, trends, regime, events):
    tr = trades[pos["trade_ref"]]
    result = "Winner" if total_r > 0 else "Break Even" if total_r == 0 else "Loser"
    tr.update({"exit_idx": li, "exit": round(exit_px, 6), "exit_reason": reason,
               "result": result, "rr": round(total_r, 2), "status": "Closed",
               "bars_held": li - pos["entry_idx"],
               "loss_analysis": _loss_analysis(pos, trends, regime, total_r, li) if total_r <= 0 else None})
    events.append({"idx": li, "kind": "exit",
                   "text": f"{pos['side'].title()} closed — {reason} ({total_r:+.2f}R)."})


def _loss_analysis(pos, trends, regime, r, exit_idx) -> Optional[str]:
    if r > 0:
        return None
    held = exit_idx - pos["entry_idx"]
    want = "Bullish" if pos["side"] == "long" else "Bearish"
    if trends.get("4H") not in (want, "n/a", "Neutral"):
        return "Higher-timeframe trend turned against the trade."
    if held <= 2:
        return "Stopped almost immediately — likely a false breakout / entry too early."
    if pos["regime"] in ("Ranging", "Extreme Volatility"):
        return "Entered in choppy / unclear conditions."
    return "Setup invalidated — price reversed into the stop."


def _zones_from_strategy(strat, offset, view_len) -> list:
    zones = []
    if strat._swing_high is not None:
        zones.append({"type": "resistance", "price": round(strat._swing_high, 6)})
    if strat._swing_low is not None:
        zones.append({"type": "support", "price": round(strat._swing_low, 6)})
    return zones


def _stats(trades: list, symbol: str) -> dict:
    closed = [t for t in trades if t.get("rr") is not None]
    rs = [t["rr"] for t in closed]
    n = len(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gp, gl = sum(wins), -sum(losses)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    longs = [t["rr"] for t in closed if t["side"] == "long"]
    shorts = [t["rr"] for t in closed if t["side"] == "short"]
    return {
        "symbol": symbol, "trades": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "profit_factor": round(gp / gl, 2) if gl else (99.0 if gp else 0.0),
        "net_r": round(sum(rs), 2),
        "max_drawdown_r": round(dd, 2),
        "avg_rr": round(sum(rs) / n, 2) if n else 0.0,
        "expectancy_r": round(sum(rs) / n, 3) if n else 0.0,
        "best_r": round(max(rs), 2) if rs else 0.0,
        "worst_r": round(min(rs), 2) if rs else 0.0,
        "long_trades": len(longs), "short_trades": len(shorts),
        "long_net_r": round(sum(longs), 2), "short_net_r": round(sum(shorts), 2),
    }


def multi_asset_stats(symbols: list, exec_tf: str = "15m", limit: int = 800) -> list:
    """Lightweight per-asset stats (trades only, no frames) for the stats panel."""
    out = []
    for sym in symbols:
        rep = build_replay(sym, exec_tf, limit)
        out.append(rep["stats"])
    return out
