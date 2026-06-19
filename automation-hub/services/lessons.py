"""Trade-history learning — turns real simulation/replay results into evidence-
based lessons, and persists them in a 'Lessons Learned' journal.

Lessons are DERIVED from measured results (regime/session/symbol breakdown,
per-trade loss analysis, quality scores) — never invented. Each lesson carries a
confidence score, the evidence it came from, a suggested fix, and a human
approval status (the bot can suggest, but only a human approves).
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- per-trade tagging (winners and losers) ----
def tag_trade(trade: dict) -> list:
    """Return the reason tags for a single (replay/sim) trade."""
    tags = []
    r = trade.get("rr") if trade.get("rr") is not None else trade.get("r", 0)
    side = trade.get("side")
    regime = trade.get("regime", "")
    score = trade.get("score")
    held = trade.get("bars_held", 0)
    exit_reason = (trade.get("exit_reason") or "").lower()
    if r is not None and r <= 0:  # losing trade
        if held <= 2 and "stop" in exit_reason:
            tags.append("Entry too early / false breakout")
        if regime in ("Ranging", "Extreme Volatility"):
            tags.append("Choppy market")
        if score is not None and score < 60:
            tags.append("Weak setup score")
        la = (trade.get("loss_analysis") or "").lower()
        if "higher-timeframe" in la or "trend" in la:
            tags.append("Trend mismatch")
        if "tight" in la:
            tags.append("Stop too tight")
        if not tags:
            tags.append("Setup invalidated")
    else:  # winning trade
        if regime == "Trending":
            tags.append("Strong trend alignment")
        if score is not None and score >= 75:
            tags.append("High-quality setup")
        for rr in (trade.get("entry_reasons") or []):
            low = rr.lower()
            if "sweep" in low:
                tags.append("Liquidity sweep timing")
            if "structure" in low or "bos" in low or "choch" in low:
                tags.append("Clean market structure")
        if (r or 0) >= 2:
            tags.append("Good reward:risk")
    return tags


# ---- aggregate lessons from a results bundle (sim or replay) ----
def lessons_from_results(results: dict, *, symbol: str, strategy: str) -> list:
    """Build aggregate, statistically-grounded lessons from a results bundle.

    ``results`` should expose: trades[], stats (win_rate/profit_factor/...),
    and optionally a diagnosis dict (worst_regime/worst_session/loss_reasons)."""
    out = []
    trades = results.get("trades") or []
    diag = results.get("diagnosis") or {}
    stats = results.get("stats") or results
    n = len(trades)
    if n < 5:
        return out  # too few trades to learn anything trustworthy

    def lesson(text, fix, confidence, evidence):
        out.append({"symbol": symbol, "strategy": strategy, "lesson": text,
                    "suggested_fix": fix, "confidence": confidence, "evidence": evidence})

    wr = stats.get("win_rate", 0)
    pf = stats.get("profit_factor", 0)

    worst_regime = diag.get("worst_regime")
    if worst_regime and worst_regime.get("net_r", 0) < 0:
        lesson(f"{symbol} {strategy} loses most in {worst_regime['name']} markets "
               f"({worst_regime['net_r']}R over {worst_regime['trades']} trades).",
               "Add a market-regime filter — skip this regime (or require a reversal setup).",
               min(95, 55 + worst_regime["trades"] * 3),
               f"{worst_regime['trades']} trades, {worst_regime['win_rate']}% win in {worst_regime['name']}")

    worst_session = diag.get("worst_session")
    if worst_session and worst_session.get("net_r", 0) < 0:
        lesson(f"{symbol} performs worst in the {worst_session['name']} session "
               f"({worst_session['net_r']}R).",
               f"Avoid trading the {worst_session['name']} session, or tighten filters there.",
               min(90, 50 + worst_session["trades"] * 3),
               f"{worst_session['trades']} trades, {worst_session['win_rate']}% win")

    if diag.get("avg_losing_setup_score") is not None and diag["avg_losing_setup_score"] < 60:
        lesson(f"Losing trades averaged a quality score of {diag['avg_losing_setup_score']}/100.",
               "Raise the minimum trade-quality score to skip these weak setups.",
               80, f"avg losing setup score {diag['avg_losing_setup_score']}")

    if wr > 55 and pf < 1.1:
        lesson("High win rate but weak profit factor — small wins, large losses.",
               "Widen the take-profit / let winners run, or cut losers earlier.",
               70, f"win rate {wr}% but profit factor {pf}")

    if diag.get("overtrading"):
        lesson("Trade frequency is high relative to edge — costs erode returns.",
               "Tighten entry filters / raise the minimum score to trade less, better.",
               65, f"{diag.get('trades_per_day')} trades/day")

    # per-trade pattern frequency (e.g. choppy losses)
    from collections import Counter
    tagc: Counter = Counter()
    for t in trades:
        if (t.get("rr") if t.get("rr") is not None else t.get("r", 0)) <= 0:
            for tag in tag_trade(t):
                tagc[tag] += 1
    for tag, count in tagc.most_common(2):
        if count >= 3:
            lesson(f"Recurring losing pattern: '{tag}' appeared in {count} losing trades.",
                   _fix_for_tag(tag), min(85, 45 + count * 5), f"{count} losing trades tagged '{tag}'")
    return out


def _fix_for_tag(tag: str) -> str:
    return {
        "Entry too early / false breakout": "Require a retest/confirmation candle before entry.",
        "Choppy market": "Disable the strategy in ranging / extreme-volatility regimes.",
        "Weak setup score": "Raise the minimum trade-quality score.",
        "Trend mismatch": "Require higher-timeframe trend alignment.",
        "Stop too tight": "Widen the ATR stop multiplier.",
    }.get(tag, "Review and tighten the entry rules for this pattern.")


# ---- persistent journal ----
class LessonStore:
    """JSON-backed 'Lessons Learned' journal with human approval status."""
    STATUSES = ("Suggested", "Tested", "Approved", "Rejected", "Archived")

    def __init__(self, path: str):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text())
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def list(self) -> list:
        return sorted(self._load().values(), key=lambda x: x.get("created_at", ""), reverse=True)

    def add_many(self, lessons: list) -> list:
        data = self._load()
        added = []
        # de-duplicate on (symbol, strategy, lesson text)
        existing = {(v["symbol"], v["strategy"], v["lesson"]) for v in data.values()}
        for ls in lessons:
            key = (ls.get("symbol"), ls.get("strategy"), ls.get("lesson"))
            if key in existing:
                continue
            lid = uuid.uuid4().hex
            rec = {**ls, "id": lid, "status": "Suggested", "tested": False,
                   "created_at": _now()}
            data[lid] = rec
            added.append(rec)
            existing.add(key)
        self._write(data)
        return added

    def set_status(self, lid: str, status: str):
        if status not in self.STATUSES:
            return None
        data = self._load()
        if lid not in data:
            return None
        data[lid]["status"] = status
        data[lid]["updated_at"] = _now()
        if status == "Tested":
            data[lid]["tested"] = True
        self._write(data)
        return data[lid]

    def weekly_count(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return sum(1 for v in self._load().values() if v.get("created_at", "") >= cutoff)

    def status_counts(self) -> dict:
        from collections import Counter
        c = Counter(v.get("status", "Suggested") for v in self._load().values())
        return dict(c)
