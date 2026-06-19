"""Evolution Engine — the bot learns, suggests, tests and versions strategies,
but NEVER changes live trading without human approval.

Pieces:
  * StrategyVersionStore  — keep v1/v2/v3… of a strategy with recorded stats.
  * UpgradeStore          — bot-generated upgrade suggestions with a strict
                            human-approval lifecycle.
  * suggest_improvements  — evidence-based suggestions from real results.
  * run_experiment        — A/B a base vs a variant with a train/test split and
                            an overfitting verdict (reuses the simulator).
  * dashboard             — aggregate widgets.

Safety: the only path to live is status == "Approved" AND an explicit human
confirmation. There is no function here that auto-applies anything to live.
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

# The required lifecycle — the bot can advance to "Backtested"/"Paper tested",
# but only a human sets "Approved".
UPGRADE_STATUSES = ("Suggested", "Testing", "Backtested", "Paper tested",
                    "Approved", "Rejected", "Archived")
BOT_ALLOWED_STATUSES = {"Testing", "Backtested", "Paper tested"}  # bot may set these
HUMAN_ONLY_STATUSES = {"Approved", "Rejected", "Archived"}        # human only


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _JsonStore:
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
        return list(self._load().values())


class StrategyVersionStore(_JsonStore):
    def versions(self, strategy: str) -> list:
        rows = [v for v in self._load().values() if v.get("strategy") == strategy]
        return sorted(rows, key=lambda v: v.get("version", 0))

    def add_version(self, strategy: str, params: dict, stats: dict, note: str = "") -> dict:
        data = self._load()
        existing = [v for v in data.values() if v.get("strategy") == strategy]
        version = max((v.get("version", 0) for v in existing), default=0) + 1
        vid = uuid.uuid4().hex
        rec = {"id": vid, "strategy": strategy, "version": version, "label": f"{strategy} v{version}",
               "params": params, "stats": stats, "note": note, "created_at": _now()}
        data[vid] = rec
        self._write(data)
        return rec

    def compare(self, strategy: str) -> dict:
        vers = self.versions(strategy)
        if not vers:
            return {"strategy": strategy, "versions": [], "best": None}
        best = max(vers, key=lambda v: (v.get("stats", {}).get("net_r", -1e9),
                                        v.get("stats", {}).get("profit_factor", 0)))
        return {"strategy": strategy, "versions": vers, "best": best["label"]}


class UpgradeStore(_JsonStore):
    def list_sorted(self) -> list:
        return sorted(self._load().values(), key=lambda u: u.get("created_at", ""), reverse=True)

    def add_many(self, suggestions: list) -> list:
        data = self._load()
        existing = {(v["strategy"], v["title"]) for v in data.values()}
        added = []
        for s in suggestions:
            if (s.get("strategy"), s.get("title")) in existing:
                continue
            uid = uuid.uuid4().hex
            rec = {**s, "id": uid, "status": "Suggested", "created_at": _now(), "history": []}
            data[uid] = rec
            added.append(rec)
            existing.add((s.get("strategy"), s.get("title")))
        self._write(data)
        return added

    def set_status(self, uid: str, status: str, *, by: str = "human") -> dict | None:
        if status not in UPGRADE_STATUSES:
            return {"error": f"invalid status {status}"}
        # the bot can only advance through testing stages, never approve/reject
        if by == "bot" and status not in BOT_ALLOWED_STATUSES:
            return {"error": "Only a human can approve, reject or archive an upgrade."}
        data = self._load()
        if uid not in data:
            return None
        data[uid]["history"].append({"status": data[uid]["status"], "at": _now(), "by": by})
        data[uid]["status"] = status
        data[uid]["updated_at"] = _now()
        self._write(data)
        return data[uid]

    def status_counts(self) -> dict:
        from collections import Counter
        return dict(Counter(v.get("status", "Suggested") for v in self._load().values()))


# ---- evidence-based suggestions ----
def suggest_improvements(results: dict, *, symbol: str, strategy: str) -> list:
    """Turn measured results into structured upgrade suggestions. Each carries a
    reason, evidence, expected benefit, risk and whether a backtest is required."""
    from services.lessons import lessons_from_results
    lessons = lessons_from_results(results, symbol=symbol, strategy=strategy)
    out = []
    for ls in lessons:
        out.append({
            "strategy": strategy, "symbol": symbol,
            "title": ls["suggested_fix"],
            "reason": ls["lesson"],
            "evidence": ls["evidence"],
            "expected_benefit": "Fewer low-quality trades / better expectancy on the affected segment.",
            "risk": "May reduce trade count; validate it doesn't overfit one symbol/period.",
            "backtest_required": True,
            "confidence": ls["confidence"],
        })
    return out


# ---- experiment lab: A/B with train/test + overfit verdict ----
def run_experiment(spec_a: dict, spec_b: dict, *, bars: int = 4000, split: float = 0.7,
                   label_a: str = "Base", label_b: str = "Variant") -> dict:
    """Simulate two specs on the SAME data, split train/test, and judge whether
    the variant is a real improvement or an overfit."""
    from data.market_data import get_bars
    from strategies.custom import simulate
    from strategies.brain import TradeBrain

    symbol = spec_a.get("symbol", "BTCUSDT")
    timeframe = spec_a.get("timeframe", "4h")
    n = max(600, min(int(bars or 4000), 10000))
    rows, source = get_bars(symbol, n=n, timeframe=timeframe)
    cut = int(len(rows) * split)
    train, test = rows[:cut], rows[cut:]
    brain = TradeBrain()

    def run(spec, segment):
        ms = int(spec.get("min_score", 60)) if spec.get("quality_filter", True) else 0
        b = brain if spec.get("quality_filter", True) else None
        r = simulate(spec, segment, brain=b, min_score=ms)
        return {"trades": r["total_trades"], "win_rate": r["win_rate"],
                "profit_factor": r["profit_factor"], "net_r": r["net_r"],
                "max_drawdown_pct": r["max_drawdown_pct"], "expectancy_r": r["expectancy_r"]}

    a_train, a_test = run(spec_a, train), run(spec_a, test)
    b_train, b_test = run(spec_b, train), run(spec_b, test)

    train_gain = b_train["net_r"] - a_train["net_r"]
    test_gain = b_test["net_r"] - a_test["net_r"]
    warnings = []
    if b_test["trades"] < 10:
        warnings.append("Variant has too few out-of-sample trades to trust.")
    if train_gain > 0 and test_gain <= 0:
        warnings.append("Variant improves on training data but NOT on unseen data — likely overfit.")
    if test_gain > 0 and b_test["profit_factor"] < 1:
        warnings.append("Out-of-sample profit factor is still below 1.")

    if test_gain > 0 and b_test["profit_factor"] >= 1 and b_test["trades"] >= 10 and not warnings:
        verdict = "improvement"
        note = "Variant improves out-of-sample and looks robust. Still validate in paper trading."
    elif train_gain > 0 and test_gain <= 0:
        verdict = "overfit"
        note = "Do not adopt — the gain disappears on unseen data."
    elif test_gain > 0:
        verdict = "marginal"
        note = "Some out-of-sample gain but with caveats — see warnings."
    else:
        verdict = "no_improvement"
        note = "Variant did not beat the base out-of-sample."

    return {
        "symbol": symbol, "timeframe": timeframe, "data_source": source,
        "split": split, "train_bars": len(train), "test_bars": len(test),
        "a": {"label": label_a, "train": a_train, "test": a_test},
        "b": {"label": label_b, "train": b_train, "test": b_test},
        "train_gain_r": round(train_gain, 2), "test_gain_r": round(test_gain, 2),
        "verdict": verdict, "note": note, "warnings": warnings,
    }
