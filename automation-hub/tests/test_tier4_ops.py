"""Tier 4 — operational hardening: daily report, backups, failure drills."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.backup import backup_now, list_backups, restore_check
from services.daily_report import DailyTasks, build_report, format_report
from services.drill import run_drills

NOW = datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)


def _hist():
    today = NOW.isoformat()
    old = (NOW - timedelta(days=30)).isoformat()
    return [{"status": "closed", "pnl": 25.0, "rr": 2.5, "closed_at": today},
            {"status": "closed", "pnl": -10.0, "rr": -1.0, "closed_at": today},
            {"status": "closed", "pnl": 40.0, "rr": 3.0, "closed_at": old}]


# ─────────────────────────── daily report ───────────────────────────
def test_build_report_slices_today_week_alltime():
    r = build_report(history=_hist(), positions=[{"symbol": "BTCUSDT", "side": "long",
                                                  "entry": 100.0}],
                     balance=10_055.0, starting_balance=10_000.0, now=NOW)
    assert r["today"] == {"trades": 2, "pnl": 15.0, "win_rate": 50.0}
    assert r["all_time"]["trades"] == 3 and r["total_pnl"] == 55.0
    assert r["open_positions"][0]["symbol"] == "BTCUSDT"


def test_format_report_is_scannable_text():
    r = build_report(history=_hist(), positions=[], balance=10_055.0,
                     starting_balance=10_000.0, now=NOW,
                     watchdog_status={"findings": []},
                     engine_status={"running": True, "mode": "live",
                                    "strategy": "Decision Brain", "entry_mode": "limit"})
    text = format_report(r)
    assert "Daily report" in text and "Balance 10055.00" in text
    assert "Watchdog: all clear" in text and "Decision Brain" in text


def test_daily_tasks_fires_once_per_day():
    sent, extras = [], []
    dt = DailyTasks(sent.append, lambda: build_report(
        history=[], positions=[], balance=10_000, starting_balance=10_000, now=NOW),
        hour=8, extra=[lambda: extras.append(1)])
    before = NOW.replace(hour=7)
    assert dt.due(before) is False
    assert dt.due(NOW) is True                      # 09:00 >= 08:00
    dt.run_once(NOW)
    assert len(sent) == 1 and len(extras) == 1
    assert dt.due(NOW) is False                     # already sent today
    assert dt.due(NOW + timedelta(days=1)) is True  # next day fires again
    off = DailyTasks(sent.append, dict, hour=-1)
    assert off.due(NOW) is False and off.start() is False   # disabled


# ─────────────────────────── backups ───────────────────────────
def test_backup_snapshots_prunes_and_restore_checks(tmp_path):
    from data.ledger import SqliteLedger
    led = SqliteLedger(str(tmp_path / "ledger.db"))
    led.log(level="info", stage="t", message="x")
    (tmp_path / "learning.json").write_text("{}")
    stamps = []
    for i in range(9):                              # 9 backups, keep 7
        r = backup_now(str(tmp_path), now=NOW + timedelta(minutes=i))
        assert r["ok"] and "ledger.db" in r["files"] and "learning.json" in r["files"]
        stamps.append(r["snapshot"])
    lst = list_backups(str(tmp_path))
    assert len(lst["backups"]) == 7                 # pruned to newest 7
    assert lst["backups"][0]["snapshot"] == stamps[-1]
    chk = restore_check(str(tmp_path), stamps[-1])
    assert chk["ok"] and chk["databases"]["ledger.db"]["ok"]
    assert restore_check(str(tmp_path), "nope")["ok"] is False


def test_backup_missing_dir_is_honest():
    assert backup_now("/nonexistent/dir/xyz")["ok"] is False


# ─────────────────────────── failure drills ───────────────────────────
def test_all_failure_drills_pass():
    res = run_drills()
    failures = [r for r in res["results"] if not r["ok"]]
    assert res["ok"], f"drills failed: {failures}"
    assert res["passed"] == res["total"] == 4
    names = {r["drill"] for r in res["results"]}
    assert names == {"crash-mid-position", "ledger-backup-restore",
                     "reconciliation", "kill-switch"}


# ─────────────────────────── endpoints ───────────────────────────
def test_tier4_endpoints():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)
    prev = client.get("/report/daily").json()
    assert "text" in prev and "report" in prev
    assert client.post("/ops/backup").status_code == 401       # secret required
    assert client.post("/ops/drill").status_code == 401
    assert "backups" in client.get("/ops/backups").json()
    drill = client.post("/ops/drill",
                        headers={"X-Webhook-Secret": "dev-webhook-secret"}).json()
    assert drill["total"] == 4 and drill["ok"] is True