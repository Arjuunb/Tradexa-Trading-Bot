"""Research Lab (#15) — an internal quant lab.

Test ideas (A/B two strategy specs on the same real data with a train/test split
and an overfit verdict), save the results, and generate a shareable report.
Builds on services.evolution.run_experiment so the numbers match the rest of the
app.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_research(name: str, spec_a: dict, spec_b: dict, *, bars: int = 4000,
                 label_a: str = "A", label_b: str = "B") -> dict:
    """Run an A/B experiment and wrap it as a saved-able research record."""
    from services.evolution import run_experiment
    exp = run_experiment(spec_a, spec_b, bars=bars, label_a=label_a, label_b=label_b)
    return {
        "id": uuid.uuid4().hex, "name": name or "Untitled experiment",
        "created_at": _now(), "experiment": exp,
        "verdict": exp.get("verdict"), "test_gain_r": exp.get("test_gain_r"),
        "symbol": exp.get("symbol"), "timeframe": exp.get("timeframe"),
    }


class ResearchStore:
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
        rows = sorted(self._load().values(), key=lambda r: r.get("created_at", ""), reverse=True)
        # list view: drop the heavy experiment payload
        return [{k: r[k] for k in ("id", "name", "created_at", "verdict", "test_gain_r",
                                    "symbol", "timeframe") if k in r} for r in rows]

    def get(self, rid: str):
        return self._load().get(rid)

    def save(self, record: dict) -> dict:
        data = self._load()
        data[record["id"]] = record
        self._write(data)
        return record

    def delete(self, rid: str) -> bool:
        data = self._load()
        if rid in data:
            del data[rid]
            self._write(data)
            return True
        return False


def report_markdown(record: dict) -> str:
    """Generate a human-readable report for a saved experiment."""
    e = record.get("experiment", {})
    a, b = e.get("a", {}), e.get("b", {})

    def row(side):
        tr, te = side.get("train", {}), side.get("test", {})
        return (f"| {side.get('label', '?')} | {tr.get('net_r', 0)} | {te.get('net_r', 0)} "
                f"| {te.get('profit_factor', 0)} | {te.get('trades', 0)} |")

    lines = [
        f"# Research — {record.get('name', 'Experiment')}",
        f"_{e.get('symbol', '?')} {e.get('timeframe', '?')} · {record.get('created_at', '')[:19].replace('T', ' ')}_",
        "",
        f"**Verdict:** {e.get('verdict', '?')} — {e.get('note', '')}",
        "",
        "| Variant | Train net R | Test net R | Test PF | Test trades |",
        "|---|---|---|---|---|",
        row(a), row(b),
        "",
        f"**Out-of-sample gain (B − A):** {e.get('test_gain_r', 0):+} R "
        f"(in-sample {e.get('train_gain_r', 0):+} R)",
        f"**Data:** {e.get('data_source', '?')} · train {e.get('train_bars', 0)} / test {e.get('test_bars', 0)} bars",
    ]
    warns = e.get("warnings", [])
    if warns:
        lines += ["", "**Warnings:**"] + [f"- {w}" for w in warns]
    return "\n".join(lines)
