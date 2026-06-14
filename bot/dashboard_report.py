"""Server-rendered Trading Bot Dashboard (stdlib-only, self-contained HTML).

Renders the full 10-panel dashboard from a completed backtest:

  1. Top header        6. Open positions
  2. Account summary    7. Risk guard
  3. Bot settings       8. Trade history
  4. Live market panel  9. Performance analytics
  5. Signal panel      10. Bot logs

Everything is derived from real engine output — the ``BacktestResult``, the
bars, and the ``EventBus`` event stream — so no panel is faked. On a serverless
host (Vercel) there is no live exchange feed, so Mode renders as *Backtest* and
the "live" panels reflect the final bar / most-recent signal of the run.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional, Sequence

from bot.data.indicators import ema, rsi
from bot.types import Bar


# --------------------------------------------------------------- formatting

def _esc(x) -> str:
    return html.escape(str(x))


def _money(v: float) -> str:
    return f"{v:,.2f}"


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def _sign_cls(v: float) -> str:
    return "pos" if v >= 0 else "neg"


def _fmt_ts(ts) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M")
    return str(ts)[:16]


# ------------------------------------------------------------------ charts

def _candles_svg(bars: Sequence[Bar], width: int = 760, height: int = 240,
                 pad: int = 28, n: int = 80) -> str:
    sample = list(bars)[-n:]
    if not sample:
        return ""
    highs = [b.high for b in sample]
    lows = [b.low for b in sample]
    hi, lo = max(highs), min(lows)
    if hi == lo:
        hi = lo + 1.0
    iw, ih = width - 2 * pad, height - 2 * pad
    n_ = len(sample)
    slot = iw / n_
    cw = max(1.0, slot * 0.6)

    def y(v: float) -> float:
        return pad + (1 - (v - lo) / (hi - lo)) * ih

    # EMA(20) overlay for the same window
    closes_all = [b.close for b in bars]
    ema20_all = ema(closes_all, 20)
    ema20 = ema20_all[-n_:] if ema20_all else []

    parts: list[str] = [
        f'<rect width="{width}" height="{height}" fill="#0d1117"/>'
    ]
    for i, b in enumerate(sample):
        cx = pad + slot * i + slot / 2
        up = b.close >= b.open
        col = "#26a69a" if up else "#ef5350"
        parts.append(
            f'<line x1="{cx:.1f}" y1="{y(b.high):.1f}" x2="{cx:.1f}" '
            f'y2="{y(b.low):.1f}" stroke="{col}" stroke-width="1"/>'
        )
        oy, cyy = y(b.open), y(b.close)
        top = min(oy, cyy)
        bh = max(1.0, abs(cyy - oy))
        parts.append(
            f'<rect x="{cx - cw / 2:.1f}" y="{top:.1f}" width="{cw:.1f}" '
            f'height="{bh:.1f}" fill="{col}"/>'
        )
    if ema20:
        pts = " ".join(
            f"{pad + slot * i + slot / 2:.1f},{y(v):.1f}"
            for i, v in enumerate(ema20)
        )
        parts.append(
            f'<polyline fill="none" stroke="#f0b90b" stroke-width="1.3" '
            f'opacity="0.9" points="{pts}"/>'
        )
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'preserveAspectRatio="none" role="img" '
            f'aria-label="Candlestick chart">{"".join(parts)}</svg>')


def _line_svg(values: Sequence[float], width: int = 760, height: int = 200,
              pad: int = 28, color: str = "#2b6cb0", fill: bool = False) -> str:
    vals = list(values)
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1.0
    iw, ih = width - 2 * pad, height - 2 * pad
    n = len(vals)

    def x(i: int) -> float:
        return pad + (i / max(n - 1, 1)) * iw

    def y(v: float) -> float:
        return pad + (1 - (v - lo) / (hi - lo)) * ih

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    body = f'<rect width="{width}" height="{height}" fill="#0d1117"/>'
    if fill:
        area = f"{pad},{pad + ih} " + pts + f" {pad + iw},{pad + ih}"
        body += f'<polygon points="{area}" fill="{color}" opacity="0.18"/>'
    body += (f'<polyline fill="none" stroke="{color}" stroke-width="1.6" '
             f'points="{pts}"/>')
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'preserveAspectRatio="none">{body}</svg>')


def _drawdown_series(equity: Sequence[float]) -> list[float]:
    out: list[float] = []
    peak = equity[0] if equity else 0.0
    for v in equity:
        if v > peak:
            peak = v
        out.append((v - peak) / peak if peak > 0 else 0.0)
    return out


# -------------------------------------------------------------- data shaping

def _consecutive_losses(trades: Sequence[dict]) -> int:
    streak = 0
    for t in reversed(trades):
        if t.get("pnl", 0) < 0:
            streak += 1
        else:
            break
    return streak


def _outcome_tag(t: dict) -> str:
    pnl = t.get("pnl", 0.0)
    r = t.get("r", 0.0)
    if pnl > 0:
        return "target hit" if r >= 1.0 else "win (partial)"
    if pnl < 0:
        return "stop-loss" if r <= -0.9 else "loss"
    return "breakeven"


def _daily_pnl(trades: Sequence[dict]) -> tuple[float, Optional[str]]:
    """Realized PnL on the most recent trading day (by exit date)."""
    by_day: dict[str, float] = {}
    for t in trades:
        xt = t.get("exit_time")
        if isinstance(xt, datetime):
            key = xt.date().isoformat()
            by_day[key] = by_day.get(key, 0.0) + t.get("pnl", 0.0)
    if not by_day:
        return 0.0, None
    last = sorted(by_day)[-1]
    return by_day[last], last


def _last_event(events: Sequence[dict], etype: str) -> Optional[dict]:
    for ev in reversed(events):
        if ev.get("type") == etype:
            return ev
    return None


# ----------------------------------------------------------------- log lines

def _log_line(ev: dict) -> tuple[str, str]:
    """Return (css_class, message) for an event."""
    t = ev.get("type")
    if t == "run_started":
        return "log-ok", (f"Connected — run {str(ev.get('run_id',''))[:8]} "
                          f"started ({ev.get('kind','')}) on "
                          f"{', '.join(ev.get('symbols', []))}")
    if t == "signal":
        return "log-sig", (f"Signal generated: {ev.get('side','').upper()} "
                          f"{ev.get('symbol','')} @ {ev.get('entry',0):.4f} "
                          f"— {ev.get('reason','')}")
    if t == "order":
        return "log-ord", (f"Order placed: {ev.get('side','').upper()} "
                          f"{ev.get('qty',0):.4f} {ev.get('symbol','')}")
    if t == "fill":
        return "log-fill", (f"Trade {ev.get('role','')}: {ev.get('side','').upper()} "
                           f"{ev.get('qty',0):.4f} {ev.get('symbol','')} "
                           f"@ {ev.get('price',0):.4f}")
    if t == "trade_closed":
        cls = "log-win" if ev.get("pnl", 0) >= 0 else "log-loss"
        return cls, (f"Trade closed: {ev.get('symbol','')} "
                    f"PnL={ev.get('pnl',0):.2f} R={ev.get('r',0):.2f}")
    if t == "risk_block":
        return "log-risk", (f"Risk block: {ev.get('symbol','')} — "
                           f"{ev.get('reason','')}")
    if t == "run_finished":
        return "log-ok", (f"Run finished — equity "
                         f"{ev.get('ending_equity',0):,.2f}")
    return "log-dim", _esc(t or "event")


# ------------------------------------------------------------------- render

def render_dashboard_html(
    *,
    result,
    bars: Sequence[Bar],
    events: Sequence[dict],
    symbol: str,
    timeframe: str = "1h",
    strategy_name: str = "sr_rejection",
    risk_cfg=None,
    starting_cash: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
    mode: str = "Backtest",
    exchange: str = "Synthetic / sample data",
    status: str = "Completed",
) -> str:
    """Render the full 10-panel dashboard to a self-contained HTML string."""
    metrics = getattr(result, "metrics", {}) or {}
    trades = list(getattr(result, "trades", []) or [])
    curve = list(getattr(result, "equity_curve", []) or [])
    eq_vals = [v for _, v in curve]

    start_eq = getattr(result, "starting_equity", starting_cash)
    end_eq = getattr(result, "ending_equity", start_eq)
    total_pl = end_eq - start_eq
    total_pl_pct = (total_pl / start_eq) if start_eq else 0.0

    # ---- indicators / market ----
    closes = [b.close for b in bars]
    last_bar = bars[-1] if bars else None
    ema20 = ema(closes, 20)[-1] if closes else 0.0
    ema50 = ema(closes, 50)[-1] if closes else 0.0
    rsi14 = rsi(closes, 14) if closes else 50.0
    last_price = closes[-1] if closes else 0.0
    vols = [b.volume for b in bars][-20:]
    avg_vol = sum(vols) / len(vols) if vols else 0.0
    candle_dir = "Bullish" if (last_bar and last_bar.close >= last_bar.open) else "Bearish"
    slip_est = last_price * slippage_bps / 10_000 if last_price else 0.0

    # ---- risk config ----
    rpt = getattr(risk_cfg, "risk_per_trade_pct", 0.01)
    mdl = getattr(risk_cfg, "max_daily_loss_pct", 0.03)
    max_pos = getattr(risk_cfg, "max_open_positions", 3)
    cooldown = getattr(risk_cfg, "cooldown_bars_after_loss", 5)
    max_daily_loss_dollars = mdl * start_eq

    # ---- account / risk-guard derived ----
    daily_pl, daily_day = _daily_pnl(trades)
    daily_loss_used = (-min(0.0, daily_pl) / max_daily_loss_dollars) if max_daily_loss_dollars else 0.0
    consec = _consecutive_losses(trades)
    max_dd = metrics.get("max_dd", 0.0)
    blk = _last_event(events, "risk_block")
    blocked_reason = blk.get("reason") if blk else "None — bot active"

    # ---- signal panel ----
    sig = _last_event(events, "signal")
    if sig:
        cur_signal = sig.get("side", "hold").upper()
        sig_reason = sig.get("reason", "")
        sig_entry = sig.get("entry", 0.0)
    else:
        cur_signal, sig_reason, sig_entry = "HOLD", "No active setup", 0.0
    sig_strength = "Strong" if "touches=3" in sig_reason or "touches=4" in sig_reason else (
        "Medium" if sig else "—")

    # ---- performance ----
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    best = max((t.get("pnl", 0) for t in trades), default=0.0)
    worst = min((t.get("pnl", 0) for t in trades), default=0.0)
    dd_series = _drawdown_series(eq_vals)

    # ====================================================================
    #  HTML assembly
    # ====================================================================
    def kv(label: str, value: str, cls: str = "") -> str:
        return (f'<div class="kv"><span class="k">{_esc(label)}</span>'
                f'<span class="v {cls}">{value}</span></div>')

    status_cls = {"Running": "ok", "Completed": "ok",
                  "Paused": "warn", "Error": "neg"}.get(status, "dim")

    # 1. HEADER
    header = f'''
    <header class="topbar">
      <div class="brand">⚡ TRADING BOT DASHBOARD</div>
      <div class="status-chips">
        <span class="chip chip-{status_cls}">● {_esc(status)}</span>
        <span class="chip">Mode: <b>{_esc(mode)}</b></span>
        <span class="chip">Exchange: <b>{_esc(exchange)}</b></span>
        <span class="chip">Updated: {_esc(_fmt_ts(datetime.now(timezone.utc)))} UTC</span>
        <button class="estop" title="Halt all trading" disabled>■ EMERGENCY STOP</button>
      </div>
    </header>'''

    # 2. ACCOUNT SUMMARY
    account = f'''
    <section class="card">
      <h2>2 · Account Summary</h2>
      <div class="grid">
        {kv("Account balance", _money(start_eq))}
        {kv("Available balance", _money(end_eq))}
        {kv("Equity", _money(end_eq))}
        {kv("Total P/L", _money(total_pl) + f" ({_pct(total_pl_pct)})", _sign_cls(total_pl))}
        {kv("Daily P/L" + (f" ({daily_day})" if daily_day else ""), _money(daily_pl), _sign_cls(daily_pl))}
        {kv("Max daily loss limit", _money(max_daily_loss_dollars) + f" ({_pct(mdl)})", "dim")}
      </div>
    </section>'''

    # 3. BOT SETTINGS
    settings = f'''
    <section class="card">
      <h2>3 · Active Bot Settings</h2>
      <div class="grid">
        {kv("Symbol", _esc(symbol))}
        {kv("Timeframe", _esc(timeframe))}
        {kv("Strategy", _esc(strategy_name))}
        {kv("Risk per trade", _pct(rpt))}
        {kv("Max trades / day", "uncapped (max " + str(max_pos) + " open)")}
        {kv("Leverage", "1× (spot)")}
      </div>
    </section>'''

    # 4. LIVE MARKET PANEL
    market = f'''
    <section class="card wide">
      <h2>4 · Live Market Panel <span class="muted">— {_esc(symbol)} {_esc(timeframe)}</span></h2>
      <div class="chart">{_candles_svg(bars)}</div>
      <div class="grid g4">
        {kv("Current price", _money(last_price))}
        {kv("EMA 20 / 50", f"{ema20:,.2f} / {ema50:,.2f}", "pos" if ema20 >= ema50 else "neg")}
        {kv("RSI(14)", f"{rsi14:.1f}", "neg" if rsi14 >= 70 else ("pos" if rsi14 <= 30 else ""))}
        {kv("Volume (last / avg20)", f"{(last_bar.volume if last_bar else 0):,.0f} / {avg_vol:,.0f}")}
        {kv("Est. slippage", f"{slip_est:,.4f} ({slippage_bps:.0f} bps)", "dim")}
        {kv("Last candle", candle_dir, "pos" if candle_dir == "Bullish" else "neg")}
      </div>
    </section>'''

    # 5. SIGNAL PANEL
    signal = f'''
    <section class="card">
      <h2>5 · Signal Panel</h2>
      <div class="bigsignal {('pos' if cur_signal == 'BUY' else 'neg' if cur_signal == 'SELL' else 'dim')}">{_esc(cur_signal)}</div>
      <div class="grid">
        {kv("Signal strength", _esc(sig_strength))}
        {kv("Entry reason", _esc(sig_reason) if sig_reason else "—")}
        {kv("Reference entry", _money(sig_entry) if sig_entry else "—")}
        {kv("Invalidation", _esc(blocked_reason) if blk else "Setup still valid")}
        {kv("Next candle", "n/a (historical replay)", "dim")}
      </div>
    </section>'''

    # 6. OPEN POSITIONS
    last_trade = trades[-1] if trades else None
    if last_trade:
        dur = ""
        et, xt = last_trade.get("entry_time"), last_trade.get("exit_time")
        if isinstance(et, datetime) and isinstance(xt, datetime):
            mins = (xt - et).total_seconds() / 60
            dur = f"{mins:,.0f} min"
        pnl = last_trade.get("pnl", 0.0)
        pos_body = f'''
      <div class="emptystate">Flat — all positions closed at end of run.</div>
      <div class="subhead">Most recent position (closed)</div>
      <div class="grid g4">
        {kv("Direction", _esc(str(last_trade.get("side","")).upper()))}
        {kv("Entry price", _money(last_trade.get("entry_price", 0)))}
        {kv("Position size", f"{last_trade.get('qty',0):,.4f}")}
        {kv("Stop loss", _money(last_trade.get("planned_sl", 0)))}
        {kv("Take profit", _money(last_trade.get("planned_tp", 0)))}
        {kv("Exit price", _money(last_trade.get("exit_price", 0)))}
        {kv("Realized P&L", _money(pnl), _sign_cls(pnl))}
        {kv("Time in trade", dur or "—")}
      </div>
      <button class="btn-close" disabled>Close trade (live only)</button>'''
    else:
        pos_body = '<div class="emptystate">No positions taken during this run.</div>'
    positions = f'''
    <section class="card wide">
      <h2>6 · Open Positions</h2>
      {pos_body}
    </section>'''

    # 7. RISK GUARD
    risk_guard = f'''
    <section class="card">
      <h2>7 · Risk Guard</h2>
      <div class="grid">
        {kv("Daily loss used", _pct(min(daily_loss_used, 1.0)) + " of limit", "neg" if daily_loss_used > 0.8 else "")}
        {kv("Consecutive losses", str(consec), "neg" if consec >= 3 else "")}
        {kv("Max drawdown", _pct(max_dd), "neg")}
        {kv("Risk exposure", "0% (flat)", "dim")}
        {kv("Cooldown after loss", f"{cooldown} bars")}
        {kv("Bot blocked", _esc(blocked_reason), "neg" if blk else "pos")}
      </div>
    </section>'''

    # 8. TRADE HISTORY
    rows = []
    for t in trades[-100:][::-1]:
        pnl = t.get("pnl", 0.0)
        rows.append(
            "<tr>"
            f"<td>{_esc(_fmt_ts(t.get('exit_time','')))}</td>"
            f"<td>{_esc(t.get('symbol',''))}</td>"
            f"<td>{_esc(str(t.get('side','')).upper())}</td>"
            f"<td>{t.get('entry_price',0):,.4f}</td>"
            f"<td>{t.get('exit_price',0):,.4f}</td>"
            f"<td class='{_sign_cls(pnl)}'>{pnl:,.2f}</td>"
            f"<td>{t.get('r',0):.2f}</td>"
            f"<td class='{_sign_cls(pnl)}'>{'WIN' if pnl >= 0 else 'LOSS'}</td>"
            f"<td class='dim'>{_esc(_outcome_tag(t))}</td>"
            "</tr>"
        )
    history = f'''
    <section class="card wide">
      <h2>8 · Trade History <span class="muted">— {len(trades)} trades</span></h2>
      <div class="tablewrap">
      <table>
        <thead><tr><th>Date/time</th><th>Symbol</th><th>Direction</th>
          <th>Entry</th><th>Exit</th><th>P&amp;L</th><th>RR</th>
          <th>Result</th><th>Tag</th></tr></thead>
        <tbody>{''.join(rows) or '<tr><td colspan="9" class="dim">No trades.</td></tr>'}</tbody>
      </table>
      </div>
    </section>'''

    # 9. PERFORMANCE ANALYTICS
    perf = f'''
    <section class="card wide">
      <h2>9 · Performance Analytics</h2>
      <div class="grid g4">
        {kv("Win rate", _pct(metrics.get("win_rate", 0)))}
        {kv("Profit factor", f"{metrics.get('profit_factor', 0):.2f}")}
        {kv("Average RR", f"{metrics.get('avg_r', 0):.2f}")}
        {kv("Total trades", str(metrics.get("num_trades", 0)))}
        {kv("Best trade", _money(best), "pos")}
        {kv("Worst trade", _money(worst), "neg")}
        {kv("Sharpe (ann.)", f"{metrics.get('sharpe', 0):.2f}")}
        {kv("CAGR", _pct(metrics.get("cagr", 0)))}
      </div>
      <div class="subhead">Equity curve</div>
      <div class="chart">{_line_svg(eq_vals, color="#26a69a", fill=True)}</div>
      <div class="subhead">Drawdown</div>
      <div class="chart">{_line_svg(dd_series, color="#ef5350", fill=True, height=140)}</div>
    </section>'''

    # 10. BOT LOGS
    log_rows = []
    for ev in list(events)[-200:]:
        cls, msg = _log_line(ev)
        ts = ev.get("ts") or ev.get("bar_ts") or ""
        log_rows.append(f'<div class="logline {cls}">'
                        f'<span class="logts">{_esc(str(ts)[:19])}</span> {_esc(msg)}</div>')
    logs = f'''
    <section class="card wide">
      <h2>10 · Bot Logs <span class="muted">— last {min(len(events), 200)} events</span></h2>
      <div class="logbox">{''.join(log_rows) or '<div class="dim">No events.</div>'}</div>
    </section>'''

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Bot Dashboard — {_esc(symbol)}</title>
<style>{_CSS}</style>
</head>
<body>
{header}
<main class="layout">
  {account}
  {settings}
  {market}
  {signal}
  {positions}
  {risk_guard}
  {history}
  {perf}
  {logs}
</main>
<footer class="foot">Rendered server-side from a {_esc(mode.lower())} run · stdlib-only · no live exchange feed on serverless host</footer>
</body>
</html>'''


_CSS = """
:root{--bg:#0a0e14;--card:#11161f;--line:#1e2733;--txt:#d6dde6;--dim:#7d8896;
--pos:#26a69a;--neg:#ef5350;--warn:#f0b90b;--accent:#2b6cb0;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:13px}
.topbar{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;
gap:10px;padding:12px 18px;background:#0d1117;border-bottom:1px solid var(--line);
position:sticky;top:0;z-index:10}
.brand{font-weight:700;letter-spacing:.5px;font-size:15px}
.status-chips{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.chip{background:#161c26;border:1px solid var(--line);border-radius:14px;
padding:4px 10px;font-size:12px;color:var(--dim)}
.chip b{color:var(--txt)}
.chip-ok{color:var(--pos);border-color:var(--pos)}
.chip-warn{color:var(--warn);border-color:var(--warn)}
.chip-neg{color:var(--neg);border-color:var(--neg)}
.estop{background:var(--neg);color:#fff;border:none;border-radius:6px;
padding:6px 12px;font-weight:700;font-size:12px;cursor:not-allowed;opacity:.85}
.layout{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;padding:16px;
max-width:1280px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card.wide{grid-column:1/-1}
.card h2{margin:0 0 12px;font-size:13px;font-weight:600;color:#aeb8c4;
text-transform:uppercase;letter-spacing:.04em}
.muted{color:var(--dim);text-transform:none;font-weight:400;letter-spacing:0}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 18px}
.grid.g4{grid-template-columns:repeat(4,1fr)}
.kv{display:flex;justify-content:space-between;gap:10px;padding:6px 0;
border-bottom:1px solid #161c26}
.kv .k{color:var(--dim)}
.kv .v{font-weight:600;text-align:right}
.pos{color:var(--pos)!important}.neg{color:var(--neg)!important}.dim{color:var(--dim)!important}
.chart{background:#0d1117;border:1px solid var(--line);border-radius:6px;
margin:6px 0 12px;overflow:hidden}
.subhead{color:var(--dim);font-size:11px;text-transform:uppercase;
letter-spacing:.05em;margin:10px 0 4px}
.bigsignal{font-size:30px;font-weight:800;text-align:center;padding:14px 0;
letter-spacing:2px}
.emptystate{color:var(--dim);padding:10px;background:#0d1117;border-radius:6px;
border:1px dashed var(--line)}
.btn-close{margin-top:10px;background:#161c26;color:var(--dim);
border:1px solid var(--line);border-radius:6px;padding:7px 12px;cursor:not-allowed}
.tablewrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:6px 8px;text-align:right;border-bottom:1px solid #161c26;white-space:nowrap}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{color:var(--dim);font-weight:500;position:sticky;top:0;background:var(--card)}
.logbox{background:#0d1117;border:1px solid var(--line);border-radius:6px;
padding:8px 10px;max-height:300px;overflow-y:auto;
font-family:ui-monospace,Menlo,monospace;font-size:11px;line-height:1.7}
.logline{white-space:nowrap}
.logts{color:#56606e;margin-right:8px}
.log-ok{color:var(--pos)}.log-sig{color:#5aa9ff}.log-ord{color:#b794f4}
.log-fill{color:#63b3ed}.log-win{color:var(--pos)}.log-loss{color:var(--neg)}
.log-risk{color:var(--warn)}.log-dim{color:var(--dim)}
.foot{color:var(--dim);text-align:center;padding:18px;font-size:11px}
@media(max-width:860px){.layout{grid-template-columns:1fr}.grid.g4{grid-template-columns:repeat(2,1fr)}}
"""
