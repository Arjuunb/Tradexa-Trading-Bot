"""Growth Journey: performance memory computed from remembered trades only —
honest empty state, real streaks/expectancy/splits, provisional-sample labels."""
from services.growth_journey import build_growth


def _t(result, rr, closed_at, strategy="Decision Brain", symbol="BTCUSDT",
       pnl=None, grade="B"):
    return {"result": result, "actual_rr": rr, "closed_at": closed_at,
            "strategy": strategy, "symbol": symbol,
            "pnl": pnl if pnl is not None else rr * 10, "grade": grade}


def test_empty_memory_is_honest():
    g = build_growth([])
    assert g["available"] is False and "first remembered trade" in g["note"]


def test_totals_streaks_and_splits():
    rows = [
        _t("win", 2.0, "2026-06-03T10:00:00", grade="A"),
        _t("win", 3.0, "2026-06-10T10:00:00", symbol="ETHUSDT"),
        _t("loss", -1.0, "2026-06-20T10:00:00"),
        _t("loss", -1.0, "2026-07-01T10:00:00", strategy="Supertrend"),
        _t("win", 2.5, "2026-07-05T10:00:00", grade="A"),
    ]
    g = build_growth(rows)
    t = g["totals"]
    assert t["trades"] == 5 and t["wins"] == 3 and t["losses"] == 2
    assert t["win_rate"] == 60.0
    assert t["net_r"] == 5.5
    assert t["expectancy_r"] == 1.1
    assert t["best_r"] == 3.0 and t["worst_r"] == -1.0
    assert t["profit_factor"] == 3.75          # 7.5R won vs 2R lost
    # streaks: W W L L W -> current +1, longest win 2, longest loss 2
    assert g["streaks"] == {"current": 1, "longest_win": 2, "longest_loss": 2}
    # monthly buckets are chronological with real win rates
    assert [m["month"] for m in g["monthly"]] == ["2026-06", "2026-07"]
    assert g["monthly"][0]["net_r"] == 4.0
    # splits sorted by net R, real names
    assert g["by_strategy"][0]["name"] == "Decision Brain"
    assert any(s["name"] == "ETHUSDT" for s in g["by_symbol"])
    assert g["grades"]["A"] == 2
    assert "early sample" in g["sample_note"]


def test_unclosed_rows_are_ignored():
    g = build_growth([{"result": None}, _t("win", 2.0, "2026-07-01T00:00:00")])
    assert g["totals"]["trades"] == 1


def test_endpoint_serves_growth():
    import sys
    sys.path.insert(0, ".")
    import webhook_api as _wa
    from fastapi.testclient import TestClient
    import app as app_module
    c = TestClient(app_module.app)
    r = c.get("/trade-memory/growth",
              headers={"X-Webhook-Secret": _wa.settings.webhook_secret})
    assert r.status_code == 200
    assert "available" in r.json()
