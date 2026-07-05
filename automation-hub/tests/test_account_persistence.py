"""Capital / equity persistence.

Proves the bug is fixed: capital survives a restart (fresh store instances on the
same HUB_DATA_DIR files) and is never reset just because the app re-seeds on
boot (which is what a logout->login on a spun-down free-tier host triggers).
"""
import pytest

from data.account_store import AccountStore
from data.ledger import SqliteLedger
from execution.paper_engine import PaperExecutionEngine


def _engine(led, acct, initial):
    p = PaperExecutionEngine(led, initial)
    p.account_store = acct
    return p


def test_seed_does_not_overwrite_saved_value():
    st = AccountStore(":memory:")
    st.seed_if_empty(10_000)
    st.update_snapshot(current_equity=12_500, available_balance=12_500, realized_pnl=2_500)
    # a second seed (as happens on every boot) must NOT reset to the default
    st.seed_if_empty(10_000)
    assert st.get()["current_equity"] == 12_500
    assert st.get()["initial_capital"] == 10_000


def test_trade_close_updates_persisted_equity():
    led = SqliteLedger(":memory:")
    acct = AccountStore(":memory:")
    acct.seed_if_empty(10_000)
    p = _engine(led, acct, 10_000)
    p.open(symbol="BTCUSDT", side="BUY", size=2.0, entry=100.0, stop=95.0)
    p.close(symbol="BTCUSDT", exit_price=110.0)          # +20 realized
    assert p.balance() == pytest.approx(10_020)
    snap = acct.get()
    assert snap["current_equity"] == pytest.approx(10_020)
    assert snap["realized_pnl"] == pytest.approx(20)
    assert snap["last_updated"] is not None


def test_capital_survives_restart_with_same_data_dir(tmp_path):
    led_path = str(tmp_path / "ledger.db")
    acct_path = str(tmp_path / "account.db")

    # session 1: trade, equity moves to 10_050
    led = SqliteLedger(led_path)
    acct = AccountStore(acct_path); acct.seed_if_empty(10_000)
    p = _engine(led, acct, acct.initial_capital())
    p.open(symbol="ETHUSDT", side="BUY", size=5.0, entry=100.0, stop=90.0)
    p.close(symbol="ETHUSDT", exit_price=110.0)          # +50 realized
    assert p.balance() == pytest.approx(10_050)

    # ---- RESTART: brand-new instances on the SAME files ----
    led2 = SqliteLedger(led_path)
    acct2 = AccountStore(acct_path)
    acct2.seed_if_empty(10_000)                          # boot re-seed — must not reset
    p2 = _engine(led2, acct2, acct2.initial_capital())
    # equity is restored from the persisted ledger + account store, NOT the default
    assert p2.balance() == pytest.approx(10_050)
    assert acct2.get()["current_equity"] == pytest.approx(10_050)
    assert acct2.get()["initial_capital"] == 10_000


def test_confirmed_initial_capital_change_resets(tmp_path):
    acct = AccountStore(str(tmp_path / "a.db")); acct.seed_if_empty(10_000)
    acct.update_snapshot(current_equity=11_000, available_balance=11_000, realized_pnl=1_000)
    r = acct.set_initial_capital(25_000, reset_account=True)
    assert r["initial_capital"] == 25_000 and r["current_equity"] == 25_000
    assert r["realized_pnl"] == 0


# ─────────────────────────── endpoints ───────────────────────────
def test_account_endpoint_shape_and_no_reset():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)

    a = client.get("/paper/account").json()
    # separated concepts present
    for k in ("initial_capital", "current_equity", "available_balance", "realized_pnl",
              "unrealized_pnl", "last_updated", "persistent"):
        assert k in a, f"missing {k}"
    # legacy keys kept
    assert "starting_balance" in a and "balance" in a

    # changing initial capital needs confirm + secret
    sec = {"X-Webhook-Secret": webhook_api.settings.webhook_secret}
    assert client.post("/paper/initial-capital", json={"amount": 5}).status_code == 401
    assert client.post("/paper/initial-capital", headers=sec, json={"amount": 5}).status_code == 400
    ok = client.post("/paper/initial-capital", headers=sec,
                     json={"amount": 20_000, "confirm": True}).json()
    assert ok["initial_capital"] == 20_000 and ok["current_equity"] == 20_000
    # a plain re-read still shows the saved value (no reset on a fresh request)
    assert client.get("/paper/account").json()["initial_capital"] == 20_000


def test_supabase_counts_as_persistent(monkeypatch):
    """Free Supabase (SUPABASE_URL+KEY) must read as persistent — otherwise the
    UI would falsely warn even when the free external DB is configured."""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import webhook_api
    app = FastAPI(); app.include_router(webhook_api.router)
    client = TestClient(app)

    monkeypatch.setenv("RENDER", "1")
    monkeypatch.delenv("HUB_DATA_DIR", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    a = client.get("/paper/account").json()
    assert a["persistent"] is False and a["storage"] == "ephemeral"
    assert "SUPABASE" in (a["warning"] or "")

    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "svc-key")
    b = client.get("/paper/account").json()
    assert b["persistent"] is True and b["storage"] == "supabase" and b["warning"] is None
