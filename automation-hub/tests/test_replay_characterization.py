"""Replay characterization gate (Sprint 4, S4.0 for the replay engine).

docs/TRADECORE_PLAN.md §6: build the gate BEFORE changing an engine. S4.4 will
replace services/replay.py's inline TP1/BE/TP2 state machine with the shared
TradeManager — a change that CAN move user-visible journal numbers. This test
pins replay's current per-trade output (side/entry/exit/sl/rr/result/
exit_reason/partial) on deterministic synthetic fixtures, so that any shift
becomes a visible, reviewable snapshot diff instead of a silent regression.

The fixtures deliberately cover the exit paths S4.4 touches:
  - "Break-even stop after partial"  (the TP1 -> partial -> BE path)
  - "Stop loss hit"

Regenerating the snapshot (ONLY when a change is intended and reviewed):
    cd automation-hub && python -m tests.test_replay_characterization --update
Then eyeball the git diff of tests/fixtures/replay_snapshot.json — that diff IS
the user-visible impact of the change.
"""
import json
import os

import pytest

SNAPSHOT = os.path.join(os.path.dirname(__file__), "fixtures", "replay_snapshot.json")

# (symbol, exec_tf, limit, strategy) — must match the snapshot keys.
CASES = [
    ("BTCUSDT", "15m", 1200, "Supply/Demand"),
    ("ETHUSDT", "15m", 1200, "Supply/Demand"),
    ("BTCUSDT", "15m", 1200, "Trend Following"),
]


def _key(sym, tf, lim, strat):
    return f"{sym}|{tf}|{lim}|{strat}"


def _closed_rows(sym, tf, lim, strat):
    """Replay's closed trades, reduced to the fields a user actually sees."""
    from services.replay import build_replay
    r = build_replay(sym, tf, lim, strategy=strat, source="demo")
    return [
        {"side": t["side"], "entry": round(t["entry"], 6), "exit": round(t["exit"], 6),
         "sl": round(t["sl"], 6), "rr": t["rr"], "result": t["result"],
         "exit_reason": t.get("exit_reason"), "partial": bool(t.get("partial"))}
        for t in r["trades"] if t.get("rr") is not None
    ]


def _build_snapshot() -> dict:
    return {_key(*c): _closed_rows(*c) for c in CASES}


def _load() -> dict:
    with open(SNAPSHOT, encoding="utf-8") as f:
        return json.load(f)


def test_snapshot_exists_and_covers_the_paths_s44_changes():
    snap = _load()
    assert set(snap) == {_key(*c) for c in CASES}
    reasons = {row["exit_reason"] for rows in snap.values() for row in rows}
    # the multi-stage partial/break-even path AND a plain stop must both be
    # represented, or the gate wouldn't actually guard S4.4.
    assert any("Break-even" in (r or "") for r in reasons), reasons
    assert any("Stop loss" in (r or "") for r in reasons), reasons
    assert sum(len(v) for v in snap.values()) >= 5


def test_replay_is_deterministic():
    """A characterization gate is only meaningful if the engine is reproducible."""
    sym, tf, lim, strat = CASES[0]
    assert _closed_rows(sym, tf, lim, strat) == _closed_rows(sym, tf, lim, strat)


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}-{c[3]}")
def test_replay_output_matches_snapshot(case):
    """The gate itself: replay's trade output must equal the committed baseline.

    If this fails after an intentional engine change, regenerate the snapshot
    and REVIEW the diff — it is the user-visible impact."""
    got = _closed_rows(*case)
    want = _load()[_key(*case)]
    assert got == want, (
        f"replay output changed for {_key(*case)}.\n"
        f"expected {len(want)} trades, got {len(got)}.\n"
        "If this change is intended, regenerate with:\n"
        "  python -m tests.test_replay_characterization --update\n"
        "and review the snapshot diff."
    )


if __name__ == "__main__":  # pragma: no cover - maintenance helper
    import sys
    if "--update" in sys.argv:
        os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
        with open(SNAPSHOT, "w", encoding="utf-8") as f:
            f.write(json.dumps(_build_snapshot(), indent=2, sort_keys=True) + "\n")
        print(f"snapshot written -> {SNAPSHOT}")
    else:
        print(__doc__)
