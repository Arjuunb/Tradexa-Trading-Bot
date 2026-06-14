"""Reusable HTML building blocks: the app shell (sidebar + topbar), KPI cards,
bot rows, and chart embeds. Server-rendered, stdlib-only, dark theme. Chart
SVGs are reused from the existing ``bot.dashboard_report`` helpers.
"""
from __future__ import annotations

import html
from typing import Sequence

from bot.dashboard_report import _candles_svg, _line_svg  # reuse tested SVG helpers

# (label, href, key)
NAV = [
    ("Overview", "/", "overview"),
    ("Bots", "/bots", "bots"),
    ("Strategies", "/strategies", "strategies"),
    ("Paper Trading", "/paper-trading", "paper"),
    ("Live Trading", "/live-trading", "live"),
    ("Risk Center", "/risk-center", "risk"),
    ("Analytics", "/analytics", "analytics"),
    ("Logs", "/logs", "logs"),
    ("Notifications", "/notifications", "notifications"),
    ("Settings", "/settings", "settings"),
]


def esc(x) -> str:
    return html.escape(str(x))


def candles(bars) -> str:
    return _candles_svg(bars)


def line(values: Sequence[float], color: str = "#26a69a", fill: bool = True) -> str:
    return _line_svg(values, color=color, fill=fill)


def kpi(label: str, value: str, cls: str = "") -> str:
    return (f'<div class="kpi"><div class="kpi-k">{esc(label)}</div>'
            f'<div class="kpi-v {cls}">{value}</div></div>')


def state_badge(state: str) -> str:
    cls = {
        "Running": "b-run", "Paper Mode": "b-paper", "Paused": "b-pause",
        "Stopped": "b-stop", "Error": "b-err", "Created": "b-new",
    }.get(state, "b-new")
    return f'<span class="badge {cls}">{esc(state)}</span>'


def page(*, title: str, active: str, body: str, app_name: str = "Automation Hub",
         user: str = "") -> str:
    nav_html = "".join(
        f'<a class="nav-item{" active" if key == active else ""}" href="{href}">{esc(label)}</a>'
        for label, href, key in NAV
    )
    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(app_name)}</title>
<style>{_CSS}</style>
</head><body>
<div class="app">
  <aside class="sidebar">
    <div class="logo">⚡ {esc(app_name)}</div>
    <nav>{nav_html}</nav>
    <form class="logout" method="post" action="/logout">
      <button type="submit">Log out{f" ({esc(user)})" if user else ""}</button>
    </form>
  </aside>
  <main class="content">{body}</main>
</div>
</body></html>'''


def topbar(title: str, right_html: str = "") -> str:
    return (f'<header class="pagehead"><h1>{esc(title)}</h1>'
            f'<div class="pagehead-right">{right_html}</div></header>')


_CSS = """
:root{--bg:#0a0e14;--panel:#11161f;--line:#1e2733;--txt:#d6dde6;--dim:#7d8896;
--pos:#26a69a;--neg:#ef5350;--warn:#f0b90b;--accent:#5aa9ff;--sidebar:#0d1117;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:13px}
a{color:inherit;text-decoration:none}
.app{display:flex;min-height:100vh}
.sidebar{width:210px;background:var(--sidebar);border-right:1px solid var(--line);
display:flex;flex-direction:column;padding:14px 0;position:sticky;top:0;height:100vh}
.logo{font-weight:700;padding:0 18px 14px;border-bottom:1px solid var(--line);margin-bottom:8px}
.nav-item{display:block;padding:9px 18px;color:var(--dim);border-left:3px solid transparent}
.nav-item:hover{background:#141a24;color:var(--txt)}
.nav-item.active{color:#fff;border-left-color:var(--accent);background:#141a24}
.logout{margin-top:auto;padding:12px 18px}
.logout button{width:100%;background:#161c26;color:var(--dim);border:1px solid var(--line);
border-radius:6px;padding:8px;cursor:pointer}
.content{flex:1;padding:18px 22px;max-width:1200px}
.pagehead{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.pagehead h1{font-size:18px;margin:0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi-k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.kpi-v{font-size:22px;font-weight:700;margin-top:6px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:16px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#aeb8c4;margin:0 0 12px}
.chart{background:#0d1117;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.pos{color:var(--pos)}.neg{color:var(--neg)}.dim{color:var(--dim)}.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:8px;border-bottom:1px solid #161c26;text-align:left}
th{color:var(--dim);font-weight:500}
.badge{padding:3px 9px;border-radius:12px;font-size:11px;font-weight:600}
.b-run{background:rgba(38,166,154,.15);color:var(--pos)}
.b-paper{background:rgba(90,169,255,.15);color:var(--accent)}
.b-pause{background:rgba(240,185,11,.15);color:var(--warn)}
.b-stop{background:rgba(125,136,150,.18);color:var(--dim)}
.b-err{background:rgba(239,83,80,.15);color:var(--neg)}
.b-new{background:#161c26;color:var(--dim)}
.btn{background:var(--accent);color:#04121f;border:none;border-radius:6px;
padding:7px 12px;font-weight:600;cursor:pointer;font-size:12px}
.btn-ghost{background:#161c26;color:var(--txt);border:1px solid var(--line)}
.btn-danger{background:var(--neg);color:#fff}
.btn-warn{background:var(--warn);color:#04121f}
form.inline{display:inline}
.rowbtns{display:flex;gap:6px;justify-content:flex-end}
input,select{background:#0d1117;border:1px solid var(--line);color:var(--txt);
border-radius:6px;padding:8px;font-size:13px;width:100%}
label{display:block;color:var(--dim);font-size:12px;margin:10px 0 4px}
.formgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:0 16px;max-width:640px}
.activity{list-style:none;margin:0;padding:0}
.activity li{padding:7px 0;border-bottom:1px solid #161c26;color:var(--dim)}
.activity li b{color:var(--txt)}
.empty{color:var(--dim);padding:10px;border:1px dashed var(--line);border-radius:6px}
.bar{height:8px;background:#161c26;border-radius:4px;overflow:hidden;margin-top:4px}
.bar>span{display:block;height:100%;background:var(--warn)}
.login{max-width:340px;margin:12vh auto;background:var(--panel);
border:1px solid var(--line);border-radius:12px;padding:26px}
.login h1{font-size:18px;margin:0 0 4px}.login p{color:var(--dim);margin:0 0 18px;font-size:12px}
.err{color:var(--neg);font-size:12px;margin-top:10px}
@media(max-width:820px){.kpis{grid-template-columns:repeat(2,1fr)}.sidebar{width:64px}
.nav-item,.logo{font-size:0}.nav-item{text-align:center}}
"""
