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

from bot.data.indicators import atr, ema, true_range
from bot.types import SignalType
from services.mtf_engine import htf_consensus
from services.regime import RegimeDetector
from strategies.smc_strategy import SMCStrategy

# Execution timeframe -> how many execution bars make one higher-tf candle.
TF_FACTORS = {
    "5m": {"15m": 3, "4h": 48, "1d": 288, "1w": 2016},
    "15m": {"4h": 16, "1d": 96, "1w": 672},
}
HTF_ORDER = ["1w", "1d", "4h", "15m"]
HTF_LABEL = {"1w": "Weekly", "1d": "Daily", "4h": "4H", "15m": "15M"}
# Normalize a macro/confirmation timeframe selector to a trend-dict label.
_HTF_NORM = {"1w": "Weekly", "1d": "Daily", "4h": "4H", "15m": "15M", "5m": "5M",
             "weekly": "Weekly", "daily": "Daily", "4hour": "4H",
             "w": "Weekly", "d": "Daily"}


def _norm_htf(tf):
    if not tf:
        return None
    return _HTF_NORM.get(str(tf).strip().lower())
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


def _directional_regime(base: str, trends: dict) -> str:
    """Fold the volatility/efficiency regime + higher-timeframe direction into one
    of the six labels the brain reasons about: Bull trend, Bear trend, Range,
    Choppy market, High volatility, Low volatility."""
    if base in ("High Volatility", "Extreme Volatility"):
        return "High volatility"
    if base == "Low Volatility":
        return "Low volatility"
    dirs = [v for v in trends.values() if v in ("Bullish", "Bearish")]
    bull = dirs.count("Bullish")
    bear = dirs.count("Bearish")
    if base == "Trending":
        if bull and bear:               # higher timeframes pull both ways
            return "Choppy market"
        return "Bull trend" if bull >= bear else "Bear trend"
    # Ranging / insufficient: conflicting HTF direction => choppy, else a clean range
    if bull and bear:
        return "Choppy market"
    return "Range"


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


# ----------------------------------------------------------------------------
# Indicator engine — every series below is CAUSAL (value at bar i uses only
# bars[:i+1]) and returns ``None`` during the warm-up window so the chart never
# draws a value that wasn't actually computed. These run on the VIEW candles
# only, so index i lines up 1:1 with candles[i].
# ----------------------------------------------------------------------------
def _ema_warm(values, n):
    """EMA series seeded by SMA(n); ``None`` until n samples seen. Causal."""
    out = [None] * len(values)
    if n < 1 or len(values) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _round_opt(seq):
    return [round(x, 6) if x is not None else None for x in seq]


def _sma_series(values, n):
    """Simple moving average; ``None`` until n samples. Causal O(N)."""
    out = [None] * len(values)
    if n < 1 or len(values) < n:
        return out
    s = sum(values[:n])
    out[n - 1] = round(s / n, 6)
    for i in range(n, len(values)):
        s += values[i] - values[i - n]
        out[i] = round(s / n, 6)
    return out


def _rsi_series(closes, n=14):
    """Wilder's RSI series; ``None`` until n+1 closes. Causal."""
    out = [None] * len(closes)
    if len(closes) < n + 1:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain, avg_loss = gains / n, losses / n
    out[n] = round(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 2) if avg_loss else 100.0
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
        out[i] = round(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 2) if avg_loss else 100.0
    return out


def _macd_series(closes, fast=12, slow=26, signal=9):
    """MACD line (EMA fast - EMA slow), signal (EMA of MACD) and histogram.
    Each list is ``None`` until its own warm-up completes. Causal."""
    n = len(closes)
    macd, sig, hist = [None] * n, [None] * n, [None] * n
    if n < slow:
        return {"macd": macd, "signal": sig, "hist": hist}
    ef, es = _ema_warm(closes, fast), _ema_warm(closes, slow)
    macd_vals, idxs = [], []
    for i in range(n):
        if ef[i] is not None and es[i] is not None:
            macd[i] = round(ef[i] - es[i], 6)
            macd_vals.append(ef[i] - es[i])
            idxs.append(i)
    sig_warm = _ema_warm(macd_vals, signal)
    for j, i in enumerate(idxs):
        if sig_warm[j] is not None:
            sig[i] = round(sig_warm[j], 6)
            hist[i] = round(macd_vals[j] - sig_warm[j], 6)
    return {"macd": macd, "signal": sig, "hist": hist}


def _atr_series(bars, n=14):
    """Wilder's ATR series aligned to ``bars``; ``None`` until seeded. Causal."""
    out = [None] * len(bars)
    if len(bars) < n + 1:
        return out
    trs = [true_range(bars[i - 1].close, bars[i]) for i in range(1, len(bars))]
    avg = sum(trs[:n]) / n          # trs[k] belongs to bars[k+1]
    out[n] = round(avg, 6)
    for k in range(n, len(trs)):
        avg = (avg * (n - 1) + trs[k]) / n
        out[k + 1] = round(avg, 6)
    return out


def _bollinger_series(closes, n=20, k=2.0):
    """Bollinger bands: mid = SMA(n), upper/lower = mid ± k·population-std.
    ``None`` until n closes. Causal."""
    import math
    mid, up, lo = [None] * len(closes), [None] * len(closes), [None] * len(closes)
    if len(closes) < n:
        return {"mid": mid, "upper": up, "lower": lo}
    for i in range(n - 1, len(closes)):
        window = closes[i - n + 1:i + 1]
        m = sum(window) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in window) / n)
        mid[i], up[i], lo[i] = round(m, 6), round(m + k * sd, 6), round(m - k * sd, 6)
    return {"mid": mid, "upper": up, "lower": lo}


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


def _label_source(source: str) -> dict:
    """Map a raw data-source string to a clear label + realness flag + warning."""
    if source in ("live (ccxt)", "local store (real)"):
        return {"label": "Binance historical data", "is_real": True, "warning": None}
    if source == "bundled sample":
        return {"label": "Bundled sample (real CSV, limited history)", "is_real": False,
                "warning": "Using a small bundled CSV — not full Binance history. Run /data/sync for real Binance data."}
    if source == "synthetic":
        return {"label": "Demo sample (synthetic)", "is_real": False,
                "warning": "Demo sample data only — not real market data. Run /data/sync to load Binance history."}
    if str(source).startswith("unavailable"):
        return {"label": "No Binance data", "is_real": False, "needs_download": True,
                "warning": "Historical data missing. Download data first."}
    return {"label": source, "is_real": False, "warning": None}


def build_replay(symbol: str, exec_tf: str = "15m", limit: int = 800,
                 start=None, end=None, strategy: str = "Supply/Demand",
                 source: str = "binance", custom_spec: dict = None,
                 macro=None, confirmation=None) -> dict:
    from data.market_data import get_bars
    from bot.data.synthetic import generate_bars
    if exec_tf not in TF_FACTORS:
        exec_tf = "15m"
    n = max(300, min(int(limit or 800), 1500))
    start_dt, end_dt = _parse_date(start), _parse_date(end)

    # When a start date is given, fetch live candles from ~1200 bars earlier so
    # the higher timeframes have history to form (ignored by non-live sources).
    since_ms = None
    if start_dt is not None:
        since_ms = int((start_dt.timestamp() - _TF_SECONDS[exec_tf] * 1200) * 1000)
    if source == "demo":
        try:
            bars, source = generate_bars(n=n + 1200, timeframe=exec_tf, seed=1), "synthetic"
        except ValueError:
            bars, source = [], "unavailable"
    else:
        # Replay defaults to REAL Binance history only — never silently fall back
        # to bundled/synthetic data. Missing data surfaces a download prompt.
        bars, source = get_bars(symbol, n=n + 1200, timeframe=exec_tf,
                                since_ms=since_ms, require_real=True)

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
        sl = _label_source(source)
        needs_dl = sl.get("needs_download", False)
        note = ("Historical data missing. Download data first." if needs_dl
                else "No data in the selected date range.")
        return {"meta": {"symbol": symbol, "timeframe": exec_tf, "data_source": source,
                         "data_source_label": sl["label"], "data_is_real": sl["is_real"],
                         "data_warning": sl["warning"] or note, "needs_download": needs_dl,
                         "strategy": strategy, "bars": 0, "start": None, "end": None,
                         "htf_available": {}, "note": note},
                "candles": [], "overlays": {}, "markers": [], "zones": [],
                "frames": [], "events": [], "trades": [], "stats": _stats([], symbol)}

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

    # --- overlays on the view (all causal, 1:1 with candles) ---
    closes_view = [b.close for b in view]
    ema8 = [round(x, 6) for x in ema(closes_view, 8)] if closes_view else []
    ema20 = [round(x, 6) for x in ema(closes_view, 20)] if closes_view else []
    ema30 = [round(x, 6) for x in ema(closes_view, 30)] if closes_view else []
    ema50 = [round(x, 6) for x in ema(closes_view, 50)] if closes_view else []
    vwap = _vwap_series(view)
    bb = _bollinger_series(closes_view, 20, 2.0)
    macd = _macd_series(closes_view)
    overlays = {
        "ema8": ema8, "ema20": ema20, "ema30": ema30, "ema50": ema50,
        "sma20": _sma_series(closes_view, 20), "sma50": _sma_series(closes_view, 50),
        "vwap": vwap,
        "bb_upper": bb["upper"], "bb_mid": bb["mid"], "bb_lower": bb["lower"],
        "rsi": _rsi_series(closes_view, 14),
        "atr": _atr_series(view, 14),
        "macd": macd["macd"], "macd_signal": macd["signal"], "macd_hist": macd["hist"],
    }
    # macro/confirmation timeframe selectors drive the multi-timeframe entry gate
    gate_tfs = tuple(x for x in (_norm_htf(macro), _norm_htf(confirmation)) if x) \
        or ("Weekly", "Daily", "4H")

    detector = RegimeDetector()
    from services.strategy_presets import make_replay_strategy
    strat, strat_err, strategy_id = make_replay_strategy(strategy, symbol, exec_tf, custom_spec)
    if strat is None:                      # bad strategy name / missing custom spec
        strat, strategy_id, strat_err = SMCStrategy(symbol), "supply_demand", strat_err
    is_smc = isinstance(strat, SMCStrategy)
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

        # --- structure events from the SMC strategy's own causal state ---
        # (other strategies don't expose this internal state; their entries are
        #  still scored, gated and marked below — just without SMC structure tags)
        sweep = struct = fvg = False
        if bar.close < bar.open:
            last_down = (li, bar)
        elif bar.close > bar.open:
            last_up = (li, bar)
        recent_sweep = recent_struct = recent_fvg = False
        if is_smc:
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
                if last_down is not None:
                    ob = last_down[1]
                    zones.append({"type": "demand", "left_idx": last_down[0],
                                  "top": round(max(ob.open, ob.close), 6), "bottom": round(ob.low, 6)})
            if strat._last_bear_struct == gi:
                struct = True
                markers.append({"idx": li, "price": round(bar.close, 6), "type": "BOS/CHoCH", "side": "bear"})
                events.append({"idx": li, "kind": "structure", "text": "Bearish break of structure (BOS/CHoCH)."})
                if last_up is not None:
                    ob = last_up[1]
                    zones.append({"type": "supply", "left_idx": last_up[0],
                                  "top": round(ob.high, 6), "bottom": round(min(ob.open, ob.close), 6)})
            if strat._last_bull_fvg == gi:
                fvg = True
                markers.append({"idx": li, "price": round(bar.close, 6), "type": "FVG", "side": "bull"})
                events.append({"idx": li, "kind": "fvg", "text": "Bullish fair-value gap (imbalance) formed."})
            if strat._last_bear_fvg == gi:
                fvg = True
                markers.append({"idx": li, "price": round(bar.close, 6), "type": "FVG", "side": "bear"})
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
        if side > 0 and is_smc and strat._swing_high is not None:
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
            if score >= SCORE_THRESHOLD and pos is None and htf_consensus(trends, side, tfs=gate_tfs)["allowed"]:
                mtf = htf_consensus(trends, side, tfs=gate_tfs)
                trigger = "Entry Confirmed"
                trade_id += 1
                entry_reasons = _entry_reasons(side, trends, recent_sweep, recent_struct, recent_fvg)
                if mtf["aligned"]:
                    entry_reasons.insert(0, mtf["reason"])
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
                    "mtf": {"aligned": mtf["aligned"], "reason": mtf["reason"]},
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
                mtf = htf_consensus(trends, side, tfs=gate_tfs)
                # an MTF conflict is the more important reason to surface
                block_reason = mtf["reason"] if (score >= SCORE_THRESHOLD and not mtf["allowed"]) \
                    else _block_reason(breakdown, near_res)
                events.append({"idx": li, "kind": "blocked",
                               "text": f"Trade blocked — {block_reason} (score {score}/100)."})

        frames.append({
            "regime": regime, "market_regime": _directional_regime(regime, trends),
            "trends": trends, "trigger": trigger,
            "score": score, "breakdown": breakdown, "blocked": blocked, "reason": block_reason,
            "vol_ratio": round(vol_ratio, 2),
        })

    # keep the most recent supply/demand zones + current swing S/R levels
    zones = zones[-8:] + (_zones_from_strategy(strat, offset, len(view)) if is_smc else [])
    stats = _stats(trades, symbol)
    sl = _label_source(source)
    from datetime import datetime, timezone
    return {
        "meta": {"symbol": symbol, "timeframe": exec_tf, "data_source": source,
                 "data_source_label": sl["label"], "data_is_real": sl["is_real"],
                 "data_warning": sl["warning"], "strategy": strategy,
                 "bars": len(view), "start": view[0].timestamp.isoformat() if view else None,
                 "end": view[-1].timestamp.isoformat() if view else None,
                 "htf_available": {HTF_LABEL[k]: (v[2] >= MIN_HTF_CANDLES) for k, v in htf_trends.items()},
                 # debug panel — proves the UI is wired to the real engine
                 "debug": {"strategy_id": strategy_id, "strategy_class": type(strat).__name__,
                           "candles_loaded": len(view), "warmup_bars": len(warm),
                           "trades_generated": len(trades), "data_source": source,
                           "mtf_timeframes": [HTF_LABEL[k] for k in htf_trends],
                           "gate_timeframes": list(gate_tfs),
                           "indicators": [k for k in overlays],
                           "computed_at": datetime.now(timezone.utc).isoformat(),
                           "error": strat_err}},
        "candles": candles, "overlays": overlays,
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
    # streaks over closed trades, in chronological order
    seq = ["W" if r > 0 else "L" if r < 0 else "B" for r in rs]
    max_w = max_l = cw = cl = 0
    for res in seq:
        cw = cw + 1 if res == "W" else 0
        cl = cl + 1 if res == "L" else 0
        max_w, max_l = max(max_w, cw), max(max_l, cl)
    cur_streak, cur_kind = 0, None
    for res in reversed(seq):
        if res == "B":
            break
        if cur_kind is None:
            cur_kind = res
        if res == cur_kind:
            cur_streak += 1
        else:
            break
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
        "max_consecutive_wins": max_w, "max_consecutive_losses": max_l,
        "current_streak": cur_streak if cur_kind == "W" else -cur_streak if cur_kind == "L" else 0,
    }


def multi_asset_stats(symbols: list, exec_tf: str = "15m", limit: int = 800) -> list:
    """Lightweight per-asset stats (trades only, no frames) for the stats panel."""
    out = []
    for sym in symbols:
        rep = build_replay(sym, exec_tf, limit)
        out.append(rep["stats"])
    return out
