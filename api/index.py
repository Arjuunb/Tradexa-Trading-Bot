"""Vercel Python serverless entry point.

Why this exists
---------------
The live SSE dashboard (``bot.dashboard``) needs a long-running ``http.server``
and a background backtest thread, which Vercel's serverless model can't host.
The *static HTML report* (``bot.reporting``), however, is a perfect fit: this
function runs a backtest on each request and streams the report straight back.

Request
-------
``GET /?symbol=BTC-USD&bars=2000&seed=1``
- ``symbol``  label + (when present) the bundled sample CSV to use
- ``bars``    synthetic-bar count when no sample is bundled (200..20000)
- ``seed``    PRNG seed for reproducible synthetic data

``GET /health`` -> ``ok``

The ``bot`` package is imported from the repo root, which ``vercel.json``
bundles via ``includeFiles`` and we add to ``sys.path`` below. The core is
pure stdlib, so the function needs no third-party packages.
"""
from __future__ import annotations

import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_bars(symbol: str, n: int, seed: int):
    """Prefer a bundled sample CSV; fall back to deterministic synthetic data."""
    safe = symbol.replace("/", "-").replace(":", "-").upper()
    sample = ROOT / "data" / "samples" / f"{safe}.csv"
    if sample.exists():
        try:
            from bot.data.csv_loader import load_csv_bars
            bars = load_csv_bars(str(sample))
            if bars:
                return bars, "bundled sample"
        except Exception:
            pass  # fall through to synthetic
    from bot.data.synthetic import generate_bars
    return generate_bars(n=n, timeframe="1h", seed=seed), "synthetic"


def _run_report_html(symbol: str, n: int, seed: int) -> str:
    from bot.backtester import Backtester
    from bot.reporting import render_report_html
    from bot.strategies import SupportResistanceRejection

    bars, source = _load_bars(symbol, n, seed)
    bt = Backtester(SupportResistanceRejection(symbol=symbol), bars)
    result = bt.run()
    title = f"Backtest — {symbol} · {len(bars)} 1h bars · {source} data"
    return render_report_html(result, title=title)


def _int_arg(q: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(q.get(key, [str(default)])[0]), hi))
    except (ValueError, TypeError):
        return default


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (Vercel/BaseHTTPRequestHandler contract)
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/").endswith("/health"):
            self._send(200, "text/plain; charset=utf-8", b"ok")
            return

        q = parse_qs(parsed.query)
        symbol = (q.get("symbol", ["BTC-USD"])[0] or "BTC-USD")[:32]
        n = _int_arg(q, "bars", 2000, 200, 20000)
        seed = _int_arg(q, "seed", 1, 0, 10_000_000)

        try:
            body = _run_report_html(symbol, n, seed).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        except Exception:
            tb = traceback.format_exc().replace("<", "&lt;")
            body = (
                "<!doctype html><meta charset='utf-8'>"
                "<h1>500 — backtest failed</h1>"
                f"<pre style='white-space:pre-wrap'>{tb}</pre>"
            ).encode("utf-8")
            self._send(500, "text/html; charset=utf-8", body)

    def log_message(self, *args) -> None:  # silence default stderr access log
        return

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
