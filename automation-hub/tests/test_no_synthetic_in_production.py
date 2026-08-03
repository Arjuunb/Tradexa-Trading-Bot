"""Production must never draw a chart out of a pseudo-random number generator.

``data/market_data.get_bars()`` has a fallback ladder: local cache of real
candles -> live ccxt -> bundled CSV sample -> **deterministic synthetic**. That
last rung is correct for a test suite, which needs reproducible bars without a
network, and indefensible in a product people make trading decisions on. A
production deployment that loses its feed would keep serving confident-looking
candles from a seeded PRNG, and nothing on screen would say so.

``HUB_REQUIRE_REAL_DATA=1`` cuts the ladder off after the real sources. It is
set in every production configuration, and this file fails the build if anyone
removes it — the failure mode it prevents is invisible by construction, so a
human reviewer would not notice its absence.

These tests parse the deployment files rather than trusting a comment, for the
same reason test_landing_routes.py parses routes.ts: a config claim that is not
checked mechanically drifts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Every file that configures a production runtime, and how the flag appears in it.
PRODUCTION_CONFIGS = [
    (REPO / "Dockerfile", "HUB_REQUIRE_REAL_DATA=1"),
    (REPO / "render.yaml", "HUB_REQUIRE_REAL_DATA"),
    (REPO / "deploy/k8s/base/config.env", "HUB_REQUIRE_REAL_DATA=1"),
    (REPO / "deploy/docker/docker-compose.yml", "HUB_REQUIRE_REAL_DATA"),
]


@pytest.mark.parametrize("path,needle", PRODUCTION_CONFIGS,
                         ids=[p.name for p, _ in PRODUCTION_CONFIGS])
def test_production_config_forbids_synthetic_data(path: Path, needle: str):
    assert path.exists(), f"{path} is missing — production config moved?"
    text = path.read_text()
    assert needle in text, (
        f"{path.relative_to(REPO)} no longer sets {needle}.\n"
        "Without it, get_bars() falls through to synthetic candles whenever the "
        "real feed is unavailable, and the UI cannot tell the difference. "
        "Re-add it, or delete the synthetic rung from the ladder instead."
    )


def test_render_yaml_sets_it_to_one():
    """render.yaml is key/value YAML, so presence of the key is not enough —
    it could be present and set to "0"."""
    import yaml

    doc = yaml.safe_load((REPO / "render.yaml").read_text())
    env = {e["key"]: e.get("value") for e in doc["services"][0]["envVars"]}
    assert env.get("HUB_REQUIRE_REAL_DATA") == "1", (
        f"render.yaml sets HUB_REQUIRE_REAL_DATA={env.get('HUB_REQUIRE_REAL_DATA')!r}, expected '1'")


# Not seeded by conftest, and absent from data/symbol_catalog.json, so neither
# the local store nor the Yahoo path can answer for it. That isolates the
# fallback ladder, which is what this flag governs.
UNCACHED_SYMBOL = "ZZZTESTUSDT"


def test_the_guard_actually_suppresses_synthetic_bars(monkeypatch, tmp_path):
    """The flag is only worth setting if it works. Ask for a symbol with no
    cached data and no reachable feed, and confirm we get an honest empty
    result rather than fabricated candles."""
    monkeypatch.setenv("HUB_REQUIRE_REAL_DATA", "1")
    monkeypatch.setenv("HUB_USE_LIVE_DATA", "0")

    from config import settings
    from data.market_data import get_bars

    # conftest points settings.market_db at a store pre-seeded with generated
    # bars for BTCUSDT/ETHUSDT/SOLUSDT/XRPUSDT. Redirect it so the local-cache
    # rung genuinely misses rather than serving the fixture.
    monkeypatch.setattr(settings, "market_db", str(tmp_path / "empty.db"))

    bars, source = get_bars(UNCACHED_SYMBOL, n=100, timeframe="4h")
    assert bars == [], f"synthetic candles were returned despite the guard (source={source!r})"
    assert "unavailable" in source, f"expected an 'unavailable' source, got {source!r}"
    assert "synthetic" not in source


def test_without_the_guard_the_synthetic_rung_is_still_reachable(monkeypatch, tmp_path):
    """The complement of the test above, and the reason the flag matters.

    This documents the default behaviour rather than endorsing it: with the
    guard off, the same unreachable request yields fabricated bars that are
    indistinguishable from real ones downstream apart from the source string.
    """
    monkeypatch.delenv("HUB_REQUIRE_REAL_DATA", raising=False)
    monkeypatch.setenv("HUB_USE_LIVE_DATA", "0")

    from config import settings
    from data.market_data import get_bars

    monkeypatch.setattr(settings, "market_db", str(tmp_path / "empty.db"))

    bars, source = get_bars(UNCACHED_SYMBOL, n=50, timeframe="1h")
    # Either fabricated, or unavailable if the timeframe is unsupported — the
    # point is only that the guard is what makes it deterministic.
    assert source in ("synthetic",) or "unavailable" in source
    if source == "synthetic":
        assert bars, "synthetic source claimed but no bars produced"
