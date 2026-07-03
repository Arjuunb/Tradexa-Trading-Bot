"""Self-learning loop — the bot studies its own losing trades and adapts.

After every closed trade the LearningBook re-reads the bot's recent record,
classifies losses into NAMED, repeated mistakes, and turns strong patterns
into bounded, reversible corrections that the live pipeline actually enforces:

    symbol-leak      one symbol keeps bleeding      -> trade it at half risk
    regime-leak      losses cluster in one regime   -> block entries in it
    low-conviction   sub-threshold entries lose     -> raise the confidence floor
    revenge-trades   entries right after a loss lose -> enforce a cooldown
    session-leak     losses cluster in certain hours -> recommendation (report)
    slipped-stops    losses far beyond -1R           -> recommendation (report)

Design principles (this is evolution, not black-box self-modification):
  * every correction carries EVIDENCE (n trades, net P&L, win rate) and a
    plain-English lesson — the /learning/report shows exactly what was
    learned, from what, and when;
  * corrections are BOUNDED (risk never below 0.5x, confidence floor never
    above +0.15) so a bad lesson can't brick the bot;
  * corrections EXPIRE (default 14 days) unless the evidence re-confirms on
    newer trades — the bot relaxes rules that stopped being true, and the
    full apply/relax history is kept as its evolution timeline.

Classification is pure (unit-testable); persistence is a JSON book.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

WINDOW = 200            # analyze at most the last N closed trades
EXPIRY_DAYS = 14        # a lesson must re-confirm within this or it relaxes
MIN_RISK_MULT = 0.5     # bounded: probation never cuts risk below half
MAX_CONF_BUMP = 0.15    # bounded: learned confidence floor cap


def _parse_ts(s) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(s))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _stats(trades: list[dict]) -> dict:
    n = len(trades)
    net = sum(t.get("pnl") or 0.0 for t in trades)
    wins = sum(1 for t in trades if (t.get("pnl") or 0.0) > 0)
    return {"trades": n, "net_pnl": round(net, 2),
            "win_rate": round(100.0 * wins / n, 1) if n else 0.0}


# ─────────────────────────── pure classification ───────────────────────────
def classify(trades: list[dict], events: Optional[dict] = None) -> list[dict]:
    """Find repeated mistakes in chronological closed ``trades``.

    ``events`` (optional) maps alert_id -> {"confidence": float, "regime": str}
    recovered from the webhook log, enabling conviction/regime lessons.
    Returns findings: {kind, key, evidence:{trades,net_pnl,win_rate}, lesson}.
    """
    findings: list[dict] = []
    closed = [t for t in trades if t.get("status", "closed") == "closed"][-WINDOW:]
    if not closed:
        return findings

    # 1. symbol-leak — a symbol with enough trades that keeps losing
    by_symbol: dict[str, list] = {}
    for t in closed:
        by_symbol.setdefault(t.get("symbol", "?"), []).append(t)
    for sym, ts in by_symbol.items():
        s = _stats(ts)
        if s["trades"] >= 5 and s["net_pnl"] < 0 and s["win_rate"] < 40:
            findings.append({"kind": "symbol-leak", "key": sym, "evidence": s,
                             "lesson": f"{sym} keeps losing ({s['win_rate']}% win over "
                                       f"{s['trades']} trades, {s['net_pnl']:+.2f}) — trade it at half risk until it recovers."})

    # 2. revenge-trades — entries shortly after a loss on the same symbol
    revenge = []
    last_loss_close: dict[str, datetime] = {}
    for t in closed:
        sym = t.get("symbol", "?")
        opened = _parse_ts(t.get("opened_at"))
        prev = last_loss_close.get(sym)
        if opened and prev and (opened - prev) <= timedelta(minutes=30):
            revenge.append(t)
        if (t.get("pnl") or 0.0) < 0:
            closed_at = _parse_ts(t.get("closed_at"))
            if closed_at:
                last_loss_close[sym] = closed_at
    s = _stats(revenge)
    if s["trades"] >= 3 and s["net_pnl"] < 0:
        findings.append({"kind": "revenge-trades", "key": "within-30m-of-a-loss", "evidence": s,
                         "lesson": f"Re-entering within 30m of a loss cost {s['net_pnl']:+.2f} over "
                                   f"{s['trades']} trades — enforce a cooldown after losses."})

    # 3. session-leak — losses concentrated in a 4h UTC bucket (report-only)
    by_bucket: dict[str, list] = {}
    for t in closed:
        opened = _parse_ts(t.get("opened_at"))
        if opened:
            b = f"{(opened.hour // 4) * 4:02d}-{(opened.hour // 4) * 4 + 4:02d} UTC"
            by_bucket.setdefault(b, []).append(t)
    for bucket, ts in by_bucket.items():
        s = _stats(ts)
        if s["trades"] >= 6 and s["net_pnl"] < 0 and s["win_rate"] < 30:
            findings.append({"kind": "session-leak", "key": bucket, "evidence": s,
                             "lesson": f"The {bucket} window loses consistently "
                                       f"({s['win_rate']}% win, {s['net_pnl']:+.2f}) — consider a session filter."})

    # 4. slipped-stops — losses far beyond -1R mean stops fill worse than planned
    slipped = [t for t in closed if (t.get("rr") or 0.0) < -1.3]
    if len(slipped) >= 3:
        s = _stats(slipped)
        findings.append({"kind": "slipped-stops", "key": "worse-than--1.3R", "evidence": s,
                         "lesson": f"{s['trades']} losses filled far beyond -1R — stops are slipping; "
                                   f"widen stops or cut size in fast markets."})

    if events:
        # 5. low-conviction leak — cheap entries lose while confident ones don't
        lo = [t for t in closed
              if (events.get(t.get("alert_id") or "", {}).get("confidence") or 1.0) < 0.65]
        hi = [t for t in closed
              if (events.get(t.get("alert_id") or "", {}).get("confidence") or 0.0) >= 0.65]
        slo, shi = _stats(lo), _stats(hi)
        if slo["trades"] >= 5 and slo["net_pnl"] < 0 and shi["net_pnl"] > 0:
            findings.append({"kind": "low-conviction", "key": "confidence<0.65", "evidence": slo,
                             "lesson": f"Low-conviction entries lost {slo['net_pnl']:+.2f} while confident ones "
                                       f"made {shi['net_pnl']:+.2f} — raise the confidence floor."})

        # 6. regime-leak — losses cluster in one market regime
        by_regime: dict[str, list] = {}
        for t in closed:
            regime = events.get(t.get("alert_id") or "", {}).get("regime") or ""
            if regime:
                by_regime.setdefault(regime, []).append(t)
        for regime, ts in by_regime.items():
            s = _stats(ts)
            if s["trades"] >= 5 and s["net_pnl"] < 0 and s["win_rate"] < 35:
                findings.append({"kind": "regime-leak", "key": regime, "evidence": s,
                                 "lesson": f"'{regime}' entries lose ({s['win_rate']}% win over {s['trades']}, "
                                           f"{s['net_pnl']:+.2f}) — block entries in this regime."})
    return findings


# ─────────────────────────── the learning book ───────────────────────────
class LearningBook:
    """Persistent lessons + the bounded corrections currently in force."""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._lock = threading.Lock()
        self.lessons: list[dict] = []          # latest findings (incl. report-only)
        self.adjustments: dict = {}            # active corrections with evidence+expiry
        self.history: list[dict] = []          # evolution timeline (applied/relaxed)
        self.updated_at: Optional[str] = None
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                self.lessons = d.get("lessons", [])
                self.adjustments = d.get("adjustments", {})
                self.history = d.get("history", [])
                self.updated_at = d.get("updated_at")
            except (OSError, json.JSONDecodeError):
                pass

    def _save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"lessons": self.lessons, "adjustments": self.adjustments,
                           "history": self.history[-200:], "updated_at": self.updated_at},
                          f, indent=1)
        except OSError:
            pass

    # ---------------------------------------------------------------- update
    def update(self, trades: list[dict], events: Optional[dict] = None,
               now: Optional[datetime] = None) -> dict:
        """Re-learn from the (newest-first) trade history. Applies new bounded
        corrections, refreshes re-confirmed ones, relaxes expired ones."""
        now = now or datetime.now(timezone.utc)
        chronological = list(reversed(trades))
        findings = classify(chronological, events)
        with self._lock:
            self.lessons = findings
            expiry = (now + timedelta(days=EXPIRY_DAYS)).isoformat()
            confirmed: set[str] = set()

            def apply(key: str, adj: dict, lesson: str) -> None:
                confirmed.add(key)
                fresh = key not in self.adjustments
                self.adjustments[key] = {**adj, "lesson": lesson, "expires_at": expiry,
                                         "learned_at": self.adjustments.get(key, {}).get("learned_at",
                                                                                          now.isoformat())}
                if fresh:
                    self.history.append({"ts": now.isoformat(), "action": "applied",
                                         "key": key, "lesson": lesson})

            for f in findings:
                ev = f["evidence"]
                if f["kind"] == "symbol-leak":
                    apply(f"symbol:{f['key']}",
                          {"type": "risk_multiplier", "symbol": f["key"],
                           "multiplier": MIN_RISK_MULT, "evidence": ev}, f["lesson"])
                elif f["kind"] == "regime-leak":
                    apply(f"regime:{f['key']}",
                          {"type": "block_regime", "regime": f["key"], "evidence": ev}, f["lesson"])
                elif f["kind"] == "low-conviction":
                    apply("confidence-floor",
                          {"type": "confidence_floor", "floor": min(0.65, 0.5 + MAX_CONF_BUMP),
                           "evidence": ev}, f["lesson"])
                elif f["kind"] == "revenge-trades":
                    apply("cooldown",
                          {"type": "cooldown_min", "minutes": 30, "evidence": ev}, f["lesson"])
                # session-leak / slipped-stops stay report-only recommendations

            # relax: not re-confirmed AND past expiry -> the bot un-learns it
            for key in list(self.adjustments):
                adj = self.adjustments[key]
                exp = _parse_ts(adj.get("expires_at"))
                if key not in confirmed and (exp is None or now > exp):
                    self.history.append({"ts": now.isoformat(), "action": "relaxed", "key": key,
                                         "lesson": f"Pattern no longer present — removed: {adj.get('lesson', key)}"})
                    del self.adjustments[key]

            self.updated_at = now.isoformat()
            self._save()
        return self.report()

    # ------------------------------------------------------------ enforcement
    def risk_multiplier(self, symbol: str) -> float:
        adj = self.adjustments.get(f"symbol:{(symbol or '').upper()}")
        return max(MIN_RISK_MULT, float(adj["multiplier"])) if adj else 1.0

    def gate(self, *, symbol: str, regime: str = "", confidence: float = 1.0,
             minutes_since_loss: Optional[float] = None) -> Optional[str]:
        """Return a human-readable block reason, or None to allow."""
        if regime and f"regime:{regime}" in self.adjustments:
            ev = self.adjustments[f"regime:{regime}"]["evidence"]
            return (f"Learned block: '{regime}' lost {ev['net_pnl']:+.2f} over "
                    f"{ev['trades']} trades ({ev['win_rate']}% win)")
        floor = self.adjustments.get("confidence-floor")
        if floor and confidence < float(floor["floor"]):
            return (f"Learned confidence floor {floor['floor']:.2f} — "
                    f"entry confidence {confidence:.2f} is below it")
        cd = self.adjustments.get("cooldown")
        if cd and minutes_since_loss is not None and minutes_since_loss < float(cd["minutes"]):
            return (f"Learned cooldown: {cd['minutes']}m after a loss "
                    f"(only {minutes_since_loss:.0f}m elapsed)")
        return None

    # ---------------------------------------------------------------- report
    def report(self) -> dict:
        return {"updated_at": self.updated_at,
                "lessons": self.lessons,
                "active_adjustments": self.adjustments,
                "evolution": self.history[-50:]}
