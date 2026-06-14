"""Static HTML report exporter — stdlib only, self-contained.

Renders a backtest's equity curve, summary stats, and trade list to a
single HTML file with an embedded SVG chart. No external CSS/JS; the
report opens fine even from a USB stick or an air-gapped machine.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


# ----------------------- helpers -----------------------

def _esc(x) -> str:
    if isinstance(x, datetime):
        return html.escape(x.isoformat())
    if isinstance(x, float):
        return f"{x:.6f}"
    return html.escape(str(x))


def _equity_svg(curve: Sequence[tuple[datetime, float]],
                width: int = 900, height: int = 320,
                pad: int = 40) -> str:
    """Render the equity curve as an SVG path."""
    if not curve:
        return '<svg width="0" height="0"></svg>'
    eq = [v for _, v in curve]
    lo, hi = min(eq), max(eq)
    if hi == lo:
        hi = lo + 1.0
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    n = len(eq)

    def x(i: int) -> float:
        return pad + (i / max(n - 1, 1)) * inner_w

    def y(v: float) -> float:
        return pad + (1 - (v - lo) / (hi - lo)) * inner_h

    pts = " ".join(f"{x(i):.2f},{y(v):.2f}" for i, v in enumerate(eq))
    # Y-axis gridlines (4)
    grid_lines: list[str] = []
    grid_text: list[str] = []
    for k in range(5):
        gv = lo + (hi - lo) * k / 4
        gy = y(gv)
        grid_lines.append(
            f'<line x1="{pad}" y1="{gy:.2f}" x2="{width - pad}" '
            f'y2="{gy:.2f}" stroke="#eee" stroke-width="1"/>'
        )
        grid_text.append(
            f'<text x="{pad - 6}" y="{gy + 4:.2f}" font-size="10" '
            f'text-anchor="end" fill="#888">{gv:,.0f}</text>'
        )
    start_lbl = curve[0][0].strftime("%Y-%m-%d")
    end_lbl = curve[-1][0].strftime("%Y-%m-%d")
    return f'''\
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" \
xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Equity curve">
  <rect width="{width}" height="{height}" fill="white"/>
  {"".join(grid_lines)}
  <polyline fill="none" stroke="#2b6cb0" stroke-width="1.8" points="{pts}"/>
  {"".join(grid_text)}
  <text x="{pad}" y="{height - 10}" font-size="10" fill="#888">{start_lbl}</text>
  <text x="{width - pad}" y="{height - 10}" font-size="10" \
text-anchor="end" fill="#888">{end_lbl}</text>
</svg>'''


# ----------------------- public API -----------------------

def render_report(
    result,
    title: str = "Backtest Report",
    output_path: str = "report.html",
) -> str:
    """Render a BacktestResult / MultiBacktestResult to a single HTML file.

    Returns the absolute path to the written file.
    """
    metrics = getattr(result, "metrics", {}) or {}
    curve = getattr(result, "equity_curve", []) or []
    trades = getattr(result, "trades", []) or []
    per_symbol = getattr(result, "per_symbol", None)

    svg = _equity_svg(curve)

    # Summary table
    summary_rows = [
        ("Starting equity", f"{result.starting_equity:,.2f}"),
        ("Ending equity", f"{result.ending_equity:,.2f}"),
        ("Total return", f"{metrics.get('total_return', 0):.2%}"),
        ("CAGR", f"{metrics.get('cagr', 0):.2%}"),
        ("Trades", f"{metrics.get('num_trades', 0)}"),
        ("Win rate", f"{metrics.get('win_rate', 0):.2%}"),
        ("Avg R", f"{metrics.get('avg_r', 0):.2f}"),
        ("Profit factor", f"{metrics.get('profit_factor', 0):.2f}"),
        ("Expectancy", f"{metrics.get('expectancy', 0):,.4f}"),
        ("Sharpe (ann.)", f"{metrics.get('sharpe', 0):.2f}"),
        ("Sortino (ann.)", f"{metrics.get('sortino', 0):.2f}"),
        ("Calmar", f"{metrics.get('calmar', 0):.2f}"),
        ("Max drawdown", f"{metrics.get('max_dd', 0):.2%}"),
    ]
    summary_html = "\n".join(
        f"  <tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in summary_rows
    )

    # Per-symbol breakdown (multi-asset)
    if per_symbol:
        rows = []
        for sym, st in sorted(per_symbol.items()):
            rows.append(
                f"  <tr><td>{_esc(sym)}</td>"
                f"<td>{_esc(st.get('num_trades', 0))}</td>"
                f"<td>{st.get('win_rate', 0):.2%}</td>"
                f"<td>{st.get('pnl', 0):,.2f}</td></tr>"
            )
        per_sym_html = (
            "<h2>Per-symbol</h2>\n<table><thead><tr>"
            "<th>Symbol</th><th>Trades</th><th>Win rate</th><th>PnL</th>"
            "</tr></thead><tbody>\n" + "\n".join(rows) + "\n</tbody></table>"
        )
    else:
        per_sym_html = ""

    # Trades table (cap to first 500 rows so the file stays small).
    trade_cap = 500
    capped = trades[:trade_cap]
    trade_rows = []
    for t in capped:
        trade_rows.append(
            "  <tr>"
            f"<td>{_esc(t.get('symbol', ''))}</td>"
            f"<td>{_esc(t.get('side', ''))}</td>"
            f"<td>{_esc(t.get('entry_time', ''))}</td>"
            f"<td>{_esc(t.get('exit_time', ''))}</td>"
            f"<td>{_esc(t.get('entry_price', 0))}</td>"
            f"<td>{_esc(t.get('exit_price', 0))}</td>"
            f"<td>{t.get('qty', 0):.4f}</td>"
            f"<td>{t.get('pnl', 0):,.2f}</td>"
            f"<td>{t.get('r', 0):.2f}</td>"
            "</tr>"
        )
    overflow_note = (
        f"<p><em>Showing first {trade_cap} of {len(trades)} trades.</em></p>"
        if len(trades) > trade_cap else ""
    )

    css = """
body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
       max-width: 1100px; margin: 24px auto; padding: 0 16px; color: #222; }
h1 { margin-bottom: 4px; }
.meta { color: #666; font-size: 13px; margin-bottom: 18px; }
table { border-collapse: collapse; width: 100%; font-size: 13px;
        margin: 14px 0 24px; }
th, td { padding: 6px 10px; text-align: left;
         border-bottom: 1px solid #eee; }
th { background: #fafafa; }
.summary { max-width: 460px; }
.summary th { width: 60%; font-weight: 500; color: #555; }
.chart { margin: 18px 0; }
.pos { color: #2f855a; }
.neg { color: #c53030; }
"""

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{_esc(title)}</title>
  <style>{css}</style>
</head>
<body>
  <h1>{_esc(title)}</h1>
  <div class="meta">Generated {generated} · {len(curve)} bars · {len(trades)} trades</div>

  <div class="chart">{svg}</div>

  <h2>Summary</h2>
  <table class="summary"><tbody>
{summary_html}
  </tbody></table>

  {per_sym_html}

  <h2>Trades</h2>
  {overflow_note}
  <table>
    <thead><tr>
      <th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th>
      <th>Entry px</th><th>Exit px</th><th>Qty</th><th>PnL</th><th>R</th>
    </tr></thead>
    <tbody>
{chr(10).join(trade_rows)}
    </tbody>
  </table>
</body>
</html>
"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    return str(out.resolve())
