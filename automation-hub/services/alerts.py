"""Alerts System (#9) — evaluate alert-worthy conditions and fan them out to
Email / Telegram / Discord.

Triggers: trade opened, trade closed, strategy underperforming, high drawdown,
extreme fear, extreme greed, funding-rate spike, large liquidations.

Channels are fail-safe and non-blocking (a dead channel never breaks the engine)
and are only attempted when configured — otherwise reported "Not connected",
never faked. Stdlib only (urllib / smtplib).
"""
from __future__ import annotations

import json
import os
import smtplib
import threading
import urllib.request
from email.mime.text import MIMEText

# severity per alert type
_SEVERITY = {
    "trade_opened": "info", "trade_closed": "info",
    "strategy_underperforming": "warning", "high_drawdown": "critical",
    "extreme_fear": "warning", "extreme_greed": "warning",
    "funding_spike": "warning", "large_liquidations": "warning",
}


# ─────────────────────────────── rule evaluation ────────────────────────────
def evaluate_alerts(ctx: dict) -> list:
    """Return the alerts that should fire for the given live context.

    ctx keys (all optional): drawdown_pct, fear_greed, funding_rate_pct,
    liquidations_usd, underperforming [{strategy, reason}], events
    [{kind: opened|closed, symbol, side, pnl}]."""
    out = []

    def add(t, title, detail):
        out.append({"type": t, "severity": _SEVERITY.get(t, "info"), "title": title, "detail": detail})

    dd = ctx.get("drawdown_pct")
    if dd is not None and dd >= ctx.get("drawdown_threshold", 10):
        add("high_drawdown", "High drawdown", f"Account drawdown is {dd:.1f}% — risk controls tightening.")

    fg = ctx.get("fear_greed")
    if fg is not None:
        if fg <= 20:
            add("extreme_fear", "Extreme fear", f"Fear & Greed at {fg} — contrarian longs / caution on shorts.")
        elif fg >= 80:
            add("extreme_greed", "Extreme greed", f"Fear & Greed at {fg} — froth risk, tighten stops.")

    fr = ctx.get("funding_rate_pct")
    if fr is not None and abs(fr) >= ctx.get("funding_threshold", 0.05):
        add("funding_spike", "Funding rate spike", f"Funding at {fr:+.3f}% — crowded {'longs' if fr > 0 else 'shorts'}.")

    liq = ctx.get("liquidations_usd")
    if liq is not None and liq >= ctx.get("liquidations_threshold", 50_000_000):
        add("large_liquidations", "Large liquidations", f"${liq/1e6:.0f}M liquidated — expect volatility.")

    for u in ctx.get("underperforming", []) or []:
        add("strategy_underperforming", "Strategy underperforming",
            f"{u.get('strategy', 'A strategy')} — {u.get('reason', 'weak metrics')}.")

    for e in ctx.get("events", []) or []:
        if e.get("kind") == "opened":
            add("trade_opened", f"Trade opened — {e.get('symbol', '')}",
                f"{e.get('side', '')} {e.get('symbol', '')}".strip())
        elif e.get("kind") == "closed":
            pnl = e.get("pnl", 0.0)
            add("trade_closed", f"Trade closed — {e.get('symbol', '')}",
                f"P&L {'+' if pnl >= 0 else ''}{pnl:.2f}")
    return out


# ─────────────────────────────── channel config ────────────────────────────
class AlertChannels:
    """Channel credentials from env (or a UI-set JSON store), never exposed."""

    def __init__(self, notifier=None, path: str | None = None):
        self.notifier = notifier
        self.path = path
        self._cache = self._load()

    def _load(self) -> dict:
        try:
            if self.path and os.path.exists(self.path):
                return json.loads(open(self.path).read())
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _val(self, key: str, env: str) -> str:
        return (self._cache.get(key) or os.environ.get(env) or "").strip()

    def save(self, cfg: dict) -> dict:
        data = self._load()
        for k in ("discord_webhook", "email_to", "smtp_host", "smtp_port", "smtp_user", "smtp_pass"):
            if cfg.get(k):
                data[k] = str(cfg[k]).strip()
        if self.path:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            open(self.path, "w").write(json.dumps(data, indent=2))
        self._cache = data
        return self.status()

    @property
    def discord_webhook(self) -> str:
        return self._val("discord_webhook", "ALERT_DISCORD_WEBHOOK")

    @property
    def email_to(self) -> str:
        return self._val("email_to", "ALERT_EMAIL_TO")

    def status(self) -> dict:
        """Which channels are connected — never exposes a secret value."""
        tg = bool(self.notifier and getattr(self.notifier, "configured", False))
        return {
            "telegram": {"connected": tg, "note": "" if tg else "Set TELEGRAM_BOT_TOKEN + chat id."},
            "discord": {"connected": bool(self.discord_webhook), "note": "" if self.discord_webhook else "Add a Discord webhook URL."},
            "email": {"connected": bool(self.email_to and self._val("smtp_host", "ALERT_SMTP_HOST")),
                      "note": "" if self.email_to else "Add SMTP host + a recipient."},
        }


# ─────────────────────────────── senders (fail-safe) ────────────────────────
def send_discord(webhook: str, text: str) -> bool:
    if not webhook:
        return False
    try:
        data = json.dumps({"content": text}).encode()
        req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310
            return 200 <= getattr(r, "status", 200) < 300
    except Exception:  # noqa: BLE001
        return False


def send_email(ch: "AlertChannels", subject: str, text: str) -> bool:
    host = ch._val("smtp_host", "ALERT_SMTP_HOST")
    to = ch.email_to
    if not host or not to:
        return False
    try:
        msg = MIMEText(text)
        msg["Subject"] = subject
        msg["From"] = ch._val("smtp_user", "ALERT_SMTP_USER") or "bot@automation-hub"
        msg["To"] = to
        port = int(ch._val("smtp_port", "ALERT_SMTP_PORT") or 587)
        with smtplib.SMTP(host, port, timeout=8) as s:
            s.starttls()
            user, pw = ch._val("smtp_user", "ALERT_SMTP_USER"), ch._val("smtp_pass", "ALERT_SMTP_PASS")
            if user and pw:
                s.login(user, pw)
            s.sendmail(msg["From"], [to], msg.as_string())
        return True
    except Exception:  # noqa: BLE001
        return False


def dispatch_alert(alert: dict, channels: AlertChannels) -> dict:
    """Send one alert to every configured channel; returns per-channel result.
    Runs the network sends on a daemon thread so it never blocks the engine."""
    text = f"[{alert.get('severity', 'info').upper()}] {alert.get('title', '')}\n{alert.get('detail', '')}".strip()
    result = {"telegram": False, "discord": False, "email": False}

    def _work():
        if channels.notifier and getattr(channels.notifier, "configured", False):
            result["telegram"] = channels.notifier.send(text)
        if channels.discord_webhook:
            result["discord"] = send_discord(channels.discord_webhook, text)
        if channels.email_to:
            result["email"] = send_email(channels, alert.get("title", "Bot alert"), text)

    threading.Thread(target=_work, daemon=True).start()
    return {"queued": True, "channels": channels.status()}
