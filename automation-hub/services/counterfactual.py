"""Counterfactual tracker — grade every veto by what actually happened next.

Every gate in the pipeline (learned blocks, event blackouts, correlation
guard, cooldowns...) refuses trades, and until now nobody ever checked whether
those refusals were RIGHT. This tracker follows each vetoed entry as a virtual
trade on the same bars the engine processes and settles the question with a
number per rule:

    saved_r > 0   the rule keeps blocking losers — it is earning its place
    saved_r < 0   the rule keeps blocking winners — it is costing money and
                  the learning book will FALSIFY it early instead of waiting
                  for the 14-day expiry

Virtual fills are the same pessimistic convention as the simulators (stop
checked before target, taker costs both sides); unresolved vetoes time out at
the last close so nothing dangles forever. Persists to JSON so grades survive
restarts. This closes the biggest open loop in the bot's self-learning:
its rules are now accountable to evidence.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

_COST_PER_SIDE = 0.0006      # taker fee + slippage, fraction of price
MAX_OPEN = 200               # open virtual trades kept per process
MAX_RESOLVED = 1000          # resolved records kept (rolling)
TIMEOUT_BARS = 200           # unresolved after this many bars -> settle at close

# a rule is judged only with enough sample
MIN_RESOLVED = 5
COSTING_R = -2.0             # cumulative saved_r below this = the rule costs money
SAVING_R = 2.0


class CounterfactualTracker:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._lock = threading.Lock()
        self.open: list[dict] = []       # virtual trades still running
        self.resolved: list[dict] = []   # settled vetoes with their r
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                self.open = d.get("open", [])[-MAX_OPEN:]
                self.resolved = d.get("resolved", [])[-MAX_RESOLVED:]
            except (OSError, json.JSONDecodeError):
                pass

    def _save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"open": self.open[-MAX_OPEN:],
                           "resolved": self.resolved[-MAX_RESOLVED:]}, f)
        except OSError:
            pass

    # ------------------------------------------------------------- recording
    def record_veto(self, *, symbol: str, side: str, entry: float, stop: float,
                    target: Optional[float] = None, rule: str, detail: str = "",
                    time: str = "") -> None:
        """Start tracking what the vetoed trade would have done. ``side`` is
        'long'/'short'; a missing target defaults to the brain's 3R."""
        if not entry or not stop or entry == stop:
            return
        risk = abs(entry - stop)
        sign = 1.0 if side == "long" else -1.0
        with self._lock:
            self.open.append({
                "symbol": symbol.upper(), "side": side, "entry": entry,
                "stop": stop, "target": target or entry + sign * 3.0 * risk,
                "risk": risk, "rule": rule, "detail": detail[:160],
                "time": time or datetime.now(timezone.utc).isoformat(),
                "bars": 0,
            })
            if len(self.open) > MAX_OPEN:
                self.open.pop(0)
            self._save()

    # -------------------------------------------------------------- on_bar
    def on_bar(self, symbol: str, bar) -> int:
        """Advance all virtual trades on this symbol; returns how many settled."""
        settled = 0
        with self._lock:
            keep = []
            for v in self.open:
                if v["symbol"] != symbol.upper():
                    keep.append(v)
                    continue
                v["bars"] += 1
                sign = 1.0 if v["side"] == "long" else -1.0
                adv = bar.low if v["side"] == "long" else bar.high
                fav = bar.high if v["side"] == "long" else bar.low
                exit_px = why = None
                if (adv - v["stop"]) * sign <= 0:
                    exit_px, why = v["stop"], "stop"        # pessimistic: stop first
                elif (fav - v["target"]) * sign >= 0:
                    exit_px, why = v["target"], "target"
                elif v["bars"] >= TIMEOUT_BARS:
                    exit_px, why = bar.close, "timeout"
                if exit_px is None:
                    keep.append(v)
                    continue
                cost_r = 2 * _COST_PER_SIDE * v["entry"] / v["risk"]
                r = (exit_px - v["entry"]) * sign / v["risk"] - cost_r
                self.resolved.append({**{k: v[k] for k in
                                         ("symbol", "side", "rule", "detail", "time")},
                                      "r": round(r, 3), "exit_reason": why,
                                      "resolved_at": bar.timestamp.isoformat()})
                settled += 1
            self.open = keep
            if settled:
                if len(self.resolved) > MAX_RESOLVED:
                    self.resolved = self.resolved[-MAX_RESOLVED:]
                self._save()
        return settled

    # --------------------------------------------------------------- scoring
    def rule_scores(self) -> dict:
        """Per rule: how much R the vetoes saved (positive = good rule)."""
        with self._lock:
            resolved = list(self.resolved)
            pending = {}
            for v in self.open:
                pending[v["rule"]] = pending.get(v["rule"], 0) + 1
        by_rule: dict[str, list] = {}
        for rec in resolved:
            by_rule.setdefault(rec["rule"], []).append(rec)
        out = {}
        for rule, recs in by_rule.items():
            saved = -sum(r["r"] for r in recs)      # blocking a -1R loser saves +1R
            n = len(recs)
            would_have_won = sum(1 for r in recs if r["r"] > 0)
            if n < MIN_RESOLVED:
                verdict = "collecting"
            elif saved >= SAVING_R:
                verdict = "saving"
            elif saved <= COSTING_R:
                verdict = "costing"
            else:
                verdict = "neutral"
            out[rule] = {"vetoes_resolved": n, "still_open": pending.pop(rule, 0),
                         "saved_r": round(saved, 2),
                         "vetoed_win_rate": round(100 * would_have_won / n, 1),
                         "verdict": verdict}
        for rule, n in pending.items():             # rules with only open vetoes
            out[rule] = {"vetoes_resolved": 0, "still_open": n, "saved_r": 0.0,
                         "vetoed_win_rate": None, "verdict": "collecting"}
        return out

    def costing_rules(self) -> list[str]:
        """Rules the evidence says are blocking winners — candidates for
        immediate falsification by the learning book."""
        return [rule for rule, s in self.rule_scores().items()
                if s["verdict"] == "costing"]

    def report(self) -> dict:
        scores = self.rule_scores()
        total_saved = round(sum(s["saved_r"] for s in scores.values()), 2)
        return {"total_saved_r": total_saved, "rules": scores,
                "open_virtual_trades": len(self.open),
                "recent_resolved": self.resolved[-15:],
                "note": ("saved_r > 0: the rule blocks losers and earns its place; "
                         "saved_r < 0: the rule blocks winners and gets falsified.")}
