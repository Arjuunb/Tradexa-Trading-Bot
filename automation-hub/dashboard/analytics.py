"""Per-bot analytics page: equity + drawdown charts, performance breakdown,
and the full trade history table. All derived from the bot's stored runtime
(populated by paper or live runs).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from bot.dashboard_report import _drawdown_series  # reuse tested helper

from config import settings
from dashboard import widgets as w


def _fmt_ts(ts) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M")
    return str(ts)[:16]


def _outcome_tag(t: dict) -> str:
    pnl, r = t.get("pnl", 0.0), t.get("r", 0.0)
    if pnl > 0:
        return "target hit" if r >= 1.0 else "win (partial)"
    if pnl < 0:
        return "stop-loss" if r <= -0.9 else "loss"
    return "breakeven"


def _selector(bots, active_id: str) -> str:
    if not bots:
        return ""
    chips = "".join(
        f'<a class="nav-item" style="display:inline-block;border-left:none;'
        f'border-radius:6px;margin-right:6px;'
        f'{"background:#141a24;color:#fff" if b.id == active_id else ""}" '
        f'href="/analytics?bot={b.id}">{w.esc(b.config.name)}</a>'
        for b in bots
    )
    return f'<div class="card"><h2>Select Bot</h2>{chips}</div>'


def render_analytics(manager, bot_id: Optional[str] = None) -> str:
    bots = [b for b in manager.list() if b.runtime.equity_curve]
    if not bots:
        return '<div class="card"><div class="empty">No completed runs yet. Start a bot to generate analytics.</div></div>'

    bot = manager.get(bot_id) if bot_id else None
    if bot is None or not bot.runtime.equity_curve:
        bot = bots[0]

    return _selector(bots, bot.id) + render_result(
        bot.config.name, bot.runtime.metrics, bot.runtime.trades,
        bot.runtime.equity_curve)


def render_result(name: str, metrics: dict, trades: list, equity_curve: list) -> str:
    """Render KPIs + equity/drawdown charts + trade table for any result-like
    data (a bot's stored runtime or a transient backtest)."""
    m = metrics or {}
    trades = trades or []
    cur = settings.currency
    eq = [v for _, v in equity_curve] if equity_curve else []
    dd = _drawdown_series(eq)
    best = max((t.get("pnl", 0) for t in trades), default=0.0)
    worst = min((t.get("pnl", 0) for t in trades), default=0.0)

    kpis = (
        '<div class="kpis">'
        + w.kpi("Win rate", f"{m.get('win_rate', 0)*100:.1f}%")
        + w.kpi("Profit factor", f"{m.get('profit_factor', 0):.2f}")
        + w.kpi("Avg RR", f"{m.get('avg_r', 0):.2f}")
        + w.kpi("Expectancy", f"{cur}{m.get('expectancy', 0):,.2f}")
        + '</div><div class="kpis">'
        + w.kpi("Total trades", str(m.get("num_trades", 0)))
        + w.kpi("Best / Worst", f"{cur}{best:,.0f} / {cur}{worst:,.0f}")
        + w.kpi("Sharpe / Sortino", f"{m.get('sharpe', 0):.2f} / {m.get('sortino', 0):.2f}")
        + w.kpi("Max drawdown", f"{m.get('max_dd', 0)*100:.2f}%", "neg")
        + '</div>'
    )

    charts = (
        f'<div class="card"><h2>Equity Curve — {w.esc(name)}</h2>'
        f'<div class="chart">{w.line(eq, color="#26a69a", fill=True)}</div></div>'
        '<div class="card"><h2>Drawdown</h2>'
        f'<div class="chart">{w.line(dd, color="#ef5350", fill=True)}</div></div>'
    )

    if trades:
        rows = "".join(
            "<tr>"
            f"<td>{w.esc(_fmt_ts(t.get('exit_time','')))}</td>"
            f"<td>{w.esc(t.get('symbol',''))}</td>"
            f"<td>{w.esc(str(t.get('side','')).upper())}</td>"
            f"<td>{t.get('entry_price',0):,.4f}</td>"
            f"<td>{t.get('exit_price',0):,.4f}</td>"
            f"<td class='{'pos' if t.get('pnl',0)>=0 else 'neg'}'>{cur}{t.get('pnl',0):,.2f}</td>"
            f"<td>{t.get('r',0):.2f}</td>"
            f"<td class='{'pos' if t.get('pnl',0)>=0 else 'neg'}'>{'WIN' if t.get('pnl',0)>=0 else 'LOSS'}</td>"
            f"<td class='dim'>{w.esc(_outcome_tag(t))}</td>"
            "</tr>"
            for t in trades[::-1]
        )
        history = (
            f'<div class="card"><h2>Trade History <span class="dim">— {len(trades)} trades</span></h2>'
            '<table><thead><tr><th>Date/time</th><th>Symbol</th><th>Direction</th>'
            '<th>Entry</th><th>Exit</th><th>P&amp;L</th><th>RR</th><th>Result</th>'
            f'<th>Tag</th></tr></thead><tbody>{rows}</tbody></table></div>'
        )
    else:
        history = '<div class="card"><h2>Trade History</h2><div class="empty">No trades.</div></div>'

    return kpis + charts + history
