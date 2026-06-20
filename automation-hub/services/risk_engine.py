"""Risk & Sizing Engine.

Three real, dependency-free quant tools that sit on top of the REAL Binance
candle store (no synthetic fallback — callers get an explicit "unavailable"
when history is missing):

  * position_size()        — fixed / percent / ATR / volatility-adjusted sizing,
                             with dollar risk, margin and a liquidation estimate.
  * correlation_matrix()   — pairwise Pearson correlation of log returns
                             (BTC/ETH/SOL/XRP …) + correlated-trade conflicts.
  * portfolio_risk()       — exposure (total / long / short / per-symbol),
                             portfolio heat and parametric Value-at-Risk built
                             from the real covariance matrix.

Everything here is pure math so it is fully unit-testable; the only I/O is the
real-data loader, which is injectable for tests.
"""
from __future__ import annotations

import math
from typing import Optional

# one-tailed normal quantiles for parametric VaR
_Z = {0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.99: 2.3263}


# ────────────────────────────────────────────────────── position sizing (#4)
def position_size(*, equity: float, entry: float, stop: Optional[float] = None,
                  side: str = "long", method: str = "percent", risk_pct: float = 0.01,
                  fixed_risk: Optional[float] = None, atr: Optional[float] = None,
                  atr_mult: float = 1.5, leverage: float = 10.0,
                  maint_margin: float = 0.005, vol_target_pct: float = 0.02) -> dict:
    """Size a trade four ways and return size, $risk, margin and a liquidation
    estimate. ``method`` ∈ {fixed, percent, atr, vol_adjusted}."""
    try:
        equity = float(equity); entry = float(entry); leverage = max(float(leverage), 1.0)
    except (TypeError, ValueError):
        return {"error": "equity, entry and leverage must be numbers"}
    if equity <= 0 or entry <= 0:
        return {"error": "equity and entry must be positive"}
    side = "short" if str(side).lower().startswith("s") else "long"

    # stop distance — ATR method derives the stop; others use a given stop price
    if method == "atr":
        if not atr or atr <= 0:
            return {"error": "ATR method needs a positive atr"}
        stop_dist = float(atr) * float(atr_mult)
        stop = entry - stop_dist if side == "long" else entry + stop_dist
    else:
        if stop is None:
            return {"error": "stop price required for this method"}
        stop_dist = abs(entry - float(stop))
    if stop_dist <= 0:
        return {"error": "stop distance must be greater than 0"}

    # dollar risk per method
    if method == "fixed":
        dollar_risk = float(fixed_risk) if fixed_risk is not None else equity * risk_pct
    elif method == "vol_adjusted":
        cur_vol = (float(atr) / entry) if atr else vol_target_pct
        scale = max(0.25, min(2.0, vol_target_pct / cur_vol)) if cur_vol > 0 else 1.0
        dollar_risk = equity * risk_pct * scale
    else:  # percent | atr
        dollar_risk = equity * risk_pct
    if dollar_risk <= 0:
        return {"error": "computed dollar risk must be positive"}

    size = dollar_risk / stop_dist
    notional = size * entry
    margin = notional / leverage
    # isolated-margin liquidation approximation
    if side == "long":
        liq = entry * (1 - 1.0 / leverage + maint_margin)
    else:
        liq = entry * (1 + 1.0 / leverage - maint_margin)
    return {
        "method": method, "side": side, "entry": round(entry, 6),
        "stop": round(float(stop), 6), "stop_distance": round(stop_dist, 6),
        "position_size": round(size, 6), "notional": round(notional, 2),
        "dollar_risk": round(dollar_risk, 2),
        "risk_pct_of_equity": round(dollar_risk / equity * 100, 3),
        "margin_required": round(margin, 2), "leverage": round(leverage, 1),
        "liquidation_estimate": round(liq, 6),
    }


# ───────────────────────────────────────────────────── correlation engine (#3)
def log_returns(closes) -> list:
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            out.append(math.log(closes[i] / closes[i - 1]))
    return out


def _mean(x):
    return sum(x) / len(x) if x else 0.0


def _stdev(x):
    n = len(x)
    if n < 2:
        return 0.0
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))


def pearson(a, b) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 3:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = _mean(a), _mean(b)
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


def _load_returns(symbol: str, timeframe: str, lookback: int, loader=None):
    """Load REAL log returns for a symbol; returns (returns|None, source)."""
    if loader is None:
        from data.market_data import get_bars
        rows, src = get_bars(symbol, n=lookback + 1, timeframe=timeframe, require_real=True)
    else:
        rows, src = loader(symbol, timeframe, lookback + 1)
    if not rows:
        return None, src
    return log_returns([b.close for b in rows]), src


def correlation_matrix(symbols: list, timeframe: str = "1d", lookback: int = 200,
                       loader=None) -> dict:
    """Pairwise Pearson correlation of log returns over the real candle store."""
    series, sources = {}, {}
    for s in symbols:
        r, src = _load_returns(s, timeframe, lookback, loader)
        sources[s] = src
        if r:
            series[s] = r
    matrix, pairs = {}, []
    for a in symbols:
        matrix[a] = {}
        for b in symbols:
            c = pearson(series[a], series[b]) if (a in series and b in series) else None
            matrix[a][b] = round(c, 3) if c is not None else None
            if a < b and c is not None:
                pairs.append({"a": a, "b": b, "correlation": round(c, 3)})
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)
    return {
        "timeframe": timeframe, "lookback": lookback, "symbols": symbols,
        "available": list(series), "matrix": matrix, "pairs": pairs,
        "daily_vol": {s: round(_stdev(series[s]), 6) for s in series},
        "data_sources": sources,
    }


def correlation_conflicts(candidate: str, open_symbols: list, *, timeframe: str = "1d",
                          lookback: int = 200, threshold: float = 0.8,
                          matrix: Optional[dict] = None, loader=None) -> dict:
    """Would opening ``candidate`` stack onto an already-correlated position?"""
    if matrix is None:
        syms = sorted({candidate, *open_symbols})
        matrix = correlation_matrix(syms, timeframe, lookback, loader)["matrix"]
    conflicts = []
    row = matrix.get(candidate) or {}
    for s in open_symbols:
        c = row.get(s)
        if c is not None and abs(c) >= threshold:
            conflicts.append({"symbol": s, "correlation": c})
    conflicts.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    reason = ("clear — no open position above the correlation threshold" if not conflicts
              else f"{candidate} is {conflicts[0]['correlation']:+.2f} correlated with open {conflicts[0]['symbol']}")
    return {"candidate": candidate, "threshold": threshold,
            "allowed": not conflicts, "conflicts": conflicts, "reason": reason}


# ──────────────────────────────────────────────────────── portfolio risk (#2)
def portfolio_risk(equity: float, positions: list, *, timeframe: str = "1d",
                   lookback: int = 200, conf: float = 0.95,
                   heat_warn: float = 0.06, exposure_warn: float = 1.0,
                   var_warn_pct: float = 5.0, loader=None) -> dict:
    """Exposure, portfolio heat and parametric Value-at-Risk from the real
    covariance matrix. ``positions`` = [{symbol, direction, notional, risk}]."""
    equity = float(equity)
    total = sum(p["notional"] for p in positions)
    long_n = sum(p["notional"] for p in positions if p["direction"] == "long")
    short_n = sum(p["notional"] for p in positions if p["direction"] == "short")
    open_risk = sum(p.get("risk", 0.0) for p in positions)
    by_symbol: dict = {}
    for p in positions:
        by_symbol[p["symbol"]] = by_symbol.get(p["symbol"], 0.0) + p["notional"]
    heat = open_risk / equity if equity > 0 else 0.0
    exposure_pct = total / equity if equity > 0 else 0.0

    # parametric 1-day VaR: w^T Σ w with Σ from real returns
    var_dollar = var_pct = None
    syms = sorted(by_symbol)
    if syms and equity > 0:
        series = {}
        for s in syms:
            r, _ = _load_returns(s, timeframe, lookback, loader)
            if r:
                series[s] = r
        if len(series) == len(syms):
            w = {s: 0.0 for s in syms}
            for p in positions:
                w[p["symbol"]] += p["notional"] * (1 if p["direction"] == "long" else -1)
            sig = {s: _stdev(series[s]) for s in syms}
            var_v = 0.0
            for i in syms:
                for j in syms:
                    cij = 1.0 if i == j else (pearson(series[i], series[j]) or 0.0)
                    var_v += w[i] * w[j] * cij * sig[i] * sig[j]
            port_sigma = math.sqrt(max(var_v, 0.0))
            z = _Z.get(round(conf, 3), 1.6449)
            var_dollar = round(z * port_sigma, 2)
            var_pct = round(var_dollar / equity * 100, 3)

    warnings = []
    if exposure_pct > exposure_warn:
        warnings.append(f"Total exposure {exposure_pct*100:.0f}% exceeds {exposure_warn*100:.0f}% of equity.")
    if heat > heat_warn:
        warnings.append(f"Portfolio heat {heat*100:.1f}% (open risk) above the {heat_warn*100:.0f}% comfort line.")
    if var_pct is not None and var_pct > var_warn_pct:
        warnings.append(f"1-day {int(conf*100)}% VaR is {var_pct:.1f}% of equity (> {var_warn_pct:.0f}%).")

    return {
        "equity": round(equity, 2),
        "total_exposure": round(total, 2), "exposure_pct": round(exposure_pct * 100, 2),
        "long_exposure": round(long_n, 2), "short_exposure": round(short_n, 2),
        "net_exposure": round(long_n - short_n, 2),
        "by_symbol": {k: round(v, 2) for k, v in by_symbol.items()},
        "open_risk": round(open_risk, 2), "portfolio_heat_pct": round(heat * 100, 2),
        "value_at_risk": var_dollar, "value_at_risk_pct": var_pct, "var_confidence": conf,
        "daily_risk_used_pct": round(heat * 100, 2),
        "warnings": warnings, "risk_level": (
            "high" if warnings else "elevated" if heat > heat_warn * 0.6 else "normal"),
    }
