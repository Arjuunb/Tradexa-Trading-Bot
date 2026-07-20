"""Compliance / audit export — a self-verifying bundle of the bot's REAL state.

Bundles the current configuration, the decision archive, the paper-trade record
and the alert log into one artefact, stamped with a SHA-256 integrity hash over
the content (sorted keys). Anyone can recompute that hash to prove the pack was
not altered after export. Paper-trading data only; nothing here is fabricated.
"""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone


def _sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def build_bundle(*, config: dict, decisions: list, trades: list, alerts: list,
                 generated_at: str | None = None) -> dict:
    content = {"config": config, "decisions": decisions, "trades": trades, "alerts": alerts}
    return {
        "meta": {
            "app": "TradeLogX Nexus",
            "kind": "compliance-audit-pack",
            "schema": 1,
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "counts": {"decisions": len(decisions), "trades": len(trades), "alerts": len(alerts)},
            "integrity_sha256": _sha256(content),
            "note": ("Paper-trading record. To verify: SHA-256 of json.dumps(content, "
                     "sort_keys=True) must equal meta.integrity_sha256."),
        },
        "content": content,
    }


def _row(cells) -> str:
    return "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in cells) + "</tr>"


def render_html(bundle: dict) -> str:
    m = bundle["meta"]
    c = bundle["content"]
    cfg = c["config"].get("editable", c["config"])
    cfg_rows = "".join(_row([k, v]) for k, v in cfg.items())
    trades = c["trades"][:100]
    trade_rows = "".join(_row([
        t.get("symbol", ""), t.get("side", ""), t.get("entry", ""), t.get("exit", "") or "—",
        t.get("pnl", "") if t.get("pnl") is not None else "—", t.get("closed_at", "") or "open",
    ]) for t in trades)
    dec = c["decisions"][:120]
    dec_rows = "".join(_row([
        d.get("ts", "")[:19].replace("T", " "), d.get("symbol", ""), d.get("timeframe", ""),
        d.get("decision", ""), d.get("score", "—"),
    ]) for d in dec)
    css = ("body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#0a0a0c;margin:32px;font-size:13px}"
           "h1{font-size:22px;margin:0 0 2px}h2{font-size:15px;margin:22px 0 6px;border-bottom:2px solid #C9A24B;padding-bottom:3px}"
           ".sub{color:#666;margin:0 0 16px}table{border-collapse:collapse;width:100%;margin:4px 0}"
           "td,th{border:1px solid #ddd;padding:4px 8px;text-align:left}th{background:#f5f5f5}"
           ".hash{font-family:monospace;font-size:11px;word-break:break-all;background:#f7f3e8;padding:8px;border:1px solid #C9A24B;border-radius:4px}"
           ".meta td:first-child{font-weight:600;width:180px}@media print{body{margin:0}}")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>TradeLogX Nexus — Audit Pack</title><style>{css}</style></head><body>
<h1>TradeLogX Nexus — Compliance Audit Pack</h1>
<p class="sub">Generated {html.escape(m['generated_at'])} · paper-trading record</p>
<table class="meta">
<tr><td>Decisions</td><td>{m['counts']['decisions']}</td></tr>
<tr><td>Trades</td><td>{m['counts']['trades']}</td></tr>
<tr><td>Alerts</td><td>{m['counts']['alerts']}</td></tr>
</table>
<h2>Integrity</h2>
<p>SHA-256 over the content (sorted keys). Recompute to verify the pack is unaltered.</p>
<div class="hash">{m['integrity_sha256']}</div>
<h2>Configuration (risk / execution)</h2>
<table><thead><tr><th>Setting</th><th>Value</th></tr></thead><tbody>{cfg_rows}</tbody></table>
<h2>Decision archive (latest {len(dec)})</h2>
<table><thead><tr><th>Time (UTC)</th><th>Symbol</th><th>TF</th><th>Decision</th><th>Score</th></tr></thead><tbody>{dec_rows}</tbody></table>
<h2>Trade record (latest {len(trades)})</h2>
<table><thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Closed</th></tr></thead><tbody>{trade_rows}</tbody></table>
<p class="sub" style="margin-top:24px">Use your browser's Print → Save as PDF to archive this report.</p>
</body></html>"""
