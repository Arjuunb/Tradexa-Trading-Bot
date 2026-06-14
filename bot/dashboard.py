"""Stdlib-only live dashboard.

Serves a single self-contained HTML page that subscribes to engine events
over Server-Sent Events (SSE). No FastAPI, no websockets — just
``http.server`` and ``EventBus``.

Endpoints
---------
- ``GET /``         single-page app (HTML + inline JS + inline CSS)
- ``GET /events``   SSE stream of JSON events from the bus
- ``GET /state``    JSON snapshot (replay of buffered events)
- ``GET /health``   ``ok``

Two convenience entry points:

- ``serve_replay(...)`` — runs a backtest in a background thread, streams
  every event to the bus so the dashboard can render the run in real time.
- ``serve(bus, ...)`` — bring-your-own-bus, useful for live runners.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from bot.events import EventBus


# ----------------------------- HTML page -----------------------------

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trading bot — live dashboard</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
         margin: 16px; color: #222; background: #fafafa; }
  h1 { margin: 0 0 12px; font-size: 18px; }
  .row { display: flex; gap: 16px; flex-wrap: wrap; }
  .card { background: white; border: 1px solid #e2e2e2; border-radius: 6px;
          padding: 12px 14px; min-width: 220px; flex: 1; }
  .k { color: #666; font-size: 11px; text-transform: uppercase;
       letter-spacing: 0.04em; }
  .v { font-size: 22px; font-weight: 600; margin-top: 4px; }
  .pos { color: #2f855a; } .neg { color: #c53030; }
  #chart { background: white; border: 1px solid #e2e2e2; border-radius: 6px;
           margin-top: 16px; }
  table { border-collapse: collapse; width: 100%; background: white;
          border: 1px solid #e2e2e2; margin-top: 16px; font-size: 12px; }
  th, td { padding: 5px 8px; text-align: left; border-bottom: 1px solid #f0f0f0; }
  th { background: #fafafa; }
  #log { max-height: 280px; overflow-y: auto; background: white;
         border: 1px solid #e2e2e2; border-radius: 6px; padding: 8px 12px;
         margin-top: 16px; font-family: ui-monospace, Menlo, monospace;
         font-size: 11px; line-height: 1.5; }
  .ev-signal { color: #2b6cb0; }
  .ev-order  { color: #805ad5; }
  .ev-fill   { color: #2f855a; }
  .ev-risk   { color: #c05621; }
  .ev-trade  { color: #1a365d; font-weight: 600; }
  .meta { color: #888; font-size: 12px; }
</style>
</head>
<body>
  <h1>Trading bot dashboard <span id="status" class="meta">connecting…</span></h1>
  <div class="row">
    <div class="card"><div class="k">Run</div><div class="v" id="run">—</div></div>
    <div class="card"><div class="k">Symbols</div><div class="v" id="syms">—</div></div>
    <div class="card"><div class="k">Equity</div><div class="v" id="eq">—</div></div>
    <div class="card"><div class="k">Return</div><div class="v" id="ret">—</div></div>
    <div class="card"><div class="k">Trades</div><div class="v" id="ntr">0</div></div>
    <div class="card"><div class="k">Bars</div><div class="v" id="nb">0</div></div>
  </div>

  <svg id="chart" width="100%" height="280" viewBox="0 0 900 280"
       preserveAspectRatio="none">
    <polyline id="curve" fill="none" stroke="#2b6cb0" stroke-width="1.5"
              points=""></polyline>
  </svg>

  <h2 style="font-size:14px;margin:16px 0 4px">Recent events</h2>
  <div id="log"></div>

  <h2 style="font-size:14px;margin:16px 0 4px">Trades</h2>
  <table id="trades">
    <thead><tr><th>Time</th><th>Symbol</th><th>Side</th>
      <th>Entry→Exit</th><th>Qty</th><th>PnL</th><th>R</th></tr></thead>
    <tbody></tbody>
  </table>

<script>
(function() {
  const $ = (id) => document.getElementById(id);
  let startEq = null, lastEq = null, nTr = 0, nBars = 0;
  const curve = [];
  const MAX_POINTS = 900;

  function fmt(n, d=2) { return n.toLocaleString(undefined,
    { minimumFractionDigits: d, maximumFractionDigits: d }); }

  function redrawChart() {
    if (!curve.length) return;
    let lo = Infinity, hi = -Infinity;
    for (const v of curve) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (hi === lo) hi = lo + 1;
    const n = curve.length;
    const pad = 10;
    const W = 900, H = 280;
    const pts = curve.map((v, i) => {
      const x = pad + (i/(n-1||1)) * (W - 2*pad);
      const y = pad + (1 - (v - lo)/(hi - lo)) * (H - 2*pad);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    $('curve').setAttribute('points', pts);
  }

  function pushLog(line, cls) {
    const el = document.createElement('div');
    el.textContent = line;
    if (cls) el.className = cls;
    const log = $('log');
    log.appendChild(el);
    while (log.childElementCount > 200) log.removeChild(log.firstChild);
    log.scrollTop = log.scrollHeight;
  }

  function addTradeRow(ev) {
    const tb = $('trades').querySelector('tbody');
    const tr = document.createElement('tr');
    const pnlCls = (ev.pnl || 0) >= 0 ? 'pos' : 'neg';
    tr.innerHTML = `<td>${ev.bar_ts || ''}</td><td>${ev.symbol||''}</td>
      <td>${ev.side||''}</td>
      <td>${fmt(ev.entry_price||0,4)} → ${fmt(ev.exit_price||0,4)}</td>
      <td>${fmt(ev.qty||0,4)}</td>
      <td class="${pnlCls}">${fmt(ev.pnl||0,2)}</td>
      <td>${fmt(ev.r||0,2)}</td>`;
    tb.insertBefore(tr, tb.firstChild);
    while (tb.childElementCount > 80) tb.removeChild(tb.lastChild);
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case 'run_started':
        $('run').textContent = (ev.run_id || '—').slice(0, 8);
        $('syms').textContent = (ev.symbols || []).join(', ') || '—';
        startEq = ev.starting_cash;
        $('eq').textContent = fmt(startEq);
        $('ret').textContent = '0.00%';
        pushLog(`[${ev.ts}] run_started ${ev.kind} (${(ev.symbols||[]).join(',')})`);
        break;
      case 'bar':
        nBars += 1; $('nb').textContent = nBars;
        lastEq = ev.equity;
        curve.push(ev.equity);
        if (curve.length > MAX_POINTS) curve.shift();
        $('eq').textContent = fmt(lastEq);
        if (startEq) {
          const r = (lastEq - startEq) / startEq;
          const el = $('ret');
          el.textContent = (r*100).toFixed(2) + '%';
          el.className = 'v ' + (r >= 0 ? 'pos' : 'neg');
        }
        // throttle redraw to every 10 bars to keep CPU low
        if (nBars % 10 === 0) redrawChart();
        break;
      case 'signal':
        pushLog(`[${ev.bar_ts}] SIGNAL ${ev.side} ${ev.symbol}`+
                ` entry=${fmt(ev.entry,4)} sl=${fmt(ev.sl,4)}`+
                ` tp=${fmt(ev.tp,4)} — ${ev.reason||''}`, 'ev-signal');
        break;
      case 'order':
        pushLog(`[order] ${ev.side} ${fmt(ev.qty,4)} ${ev.symbol}`,
                'ev-order');
        break;
      case 'fill':
        pushLog(`[fill/${ev.role}] ${ev.side} ${fmt(ev.qty,4)} `+
                `${ev.symbol} @ ${fmt(ev.price,4)}`, 'ev-fill');
        break;
      case 'risk_block':
        pushLog(`[risk_block] ${ev.symbol} — ${ev.reason}`, 'ev-risk');
        break;
      case 'trade_closed':
        nTr += 1; $('ntr').textContent = nTr;
        addTradeRow(ev);
        pushLog(`[trade] ${ev.symbol} ${ev.side} pnl=${fmt(ev.pnl,2)} `+
                `R=${fmt(ev.r,2)}`, 'ev-trade');
        break;
      case 'run_finished':
        pushLog(`[${ev.ts}] run_finished equity=${fmt(ev.ending_equity)}`);
        redrawChart();
        $('status').textContent = 'finished';
        break;
    }
  }

  // Replay buffered events first so late-loaders see history.
  fetch('/state').then(r => r.json()).then(state => {
    (state.events || []).forEach(handleEvent);
    redrawChart();
  });

  const src = new EventSource('/events');
  src.onopen = () => { $('status').textContent = 'live'; };
  src.onerror = () => { $('status').textContent = 'disconnected'; };
  src.onmessage = (m) => {
    try { handleEvent(JSON.parse(m.data)); } catch (e) {}
  };
})();
</script>
</body>
</html>
"""


# ----------------------------- server --------------------------------

class _DashboardHandler(BaseHTTPRequestHandler):
    # bus and page get attached by serve()
    bus: EventBus = None  # type: ignore[assignment]
    stop_flag: threading.Event = None  # type: ignore[assignment]

    # Silence the default access log unless someone explicitly wants it.
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _send(self, code: int, ctype: str, body: bytes,
              extra_headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
        elif path == "/health":
            self._send(200, "text/plain", b"ok")
        elif path == "/state":
            payload = json.dumps({"events": self.bus.replay()},
                                 default=str).encode("utf-8")
            self._send(200, "application/json", payload)
        elif path == "/events":
            self._serve_sse()
        else:
            self._send(404, "text/plain", b"not found")

    # --- SSE ---
    def _serve_sse(self) -> None:
        q: queue.Queue = queue.Queue(maxsize=1000)

        def on_event(ev: dict) -> None:
            # Drop oldest on overflow rather than block the engine.
            try:
                q.put_nowait(ev)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(ev)
                except queue.Empty:
                    pass

        unsub = self.bus.subscribe(on_event)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            # Replay buffered events so late connections see history.
            for ev in self.bus.replay():
                self.wfile.write(
                    f"data: {json.dumps(ev, default=str)}\n\n".encode("utf-8")
                )
            self.wfile.flush()
            last_ping = time.time()
            while not (self.stop_flag and self.stop_flag.is_set()):
                try:
                    ev = q.get(timeout=1.0)
                    self.wfile.write(
                        f"data: {json.dumps(ev, default=str)}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()
                except queue.Empty:
                    # Heartbeat every 15s so proxies don't kill the connection.
                    if time.time() - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            unsub()


def _make_handler(bus: EventBus, stop_flag: threading.Event) -> type:
    """Return a subclass with the bus/stop_flag attached as class attrs."""
    return type("BoundHandler", (_DashboardHandler,), {
        "bus": bus, "stop_flag": stop_flag,
    })


def serve(
    bus: EventBus,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    blocking: bool = True,
) -> ThreadingHTTPServer:
    """Start the dashboard HTTP server bound to ``bus``.

    Returns the server instance. If ``blocking`` is False, the caller is
    responsible for stopping the server (call ``server.shutdown()``).
    """
    stop_flag = threading.Event()
    handler = _make_handler(bus, stop_flag)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"

    if open_browser:
        # Defer open slightly so the server is ready when the tab loads.
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    if blocking:
        print(f"Dashboard live at {url}  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            stop_flag.set()
            server.shutdown()
    else:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def serve_replay(
    strategy_factory: Callable,
    bars: list,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Run a backtest in a background thread, stream events to the dashboard."""
    from bot.backtester import Backtester
    bus = EventBus()
    strat = strategy_factory()
    bt = Backtester(strat, bars, bus=bus)

    def _run() -> None:
        # Tiny pause so the browser tab is open before we flood the bus.
        time.sleep(0.6)
        bt.run()

    threading.Thread(target=_run, daemon=True).start()
    serve(bus, host=host, port=port, open_browser=open_browser, blocking=True)
