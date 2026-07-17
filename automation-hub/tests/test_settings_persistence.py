"""Durable per-user settings via the Supabase mirror.

The bug: SQLite user_settings live under HUB_DATA_DIR, which is ephemeral on a
free host, so a restart wiped them and every login showed defaults. The mirror
makes SQLite a cache and Supabase the durable source. A fake in-memory mirror
stands in for Supabase so the tests never touch the network.
"""
from database.store import SqliteStore


class FakeMirror:
    """Duck-typed stand-in for SupabaseSettingsStore."""
    def __init__(self):
        self.rows = {}

    def get(self, username, namespace):
        return self.rows.get((username, namespace))

    def set(self, username, namespace, data):
        self.rows[(username, namespace)] = dict(data)

    def delete(self, username, namespace=None):
        if namespace is None:
            self.rows = {k: v for k, v in self.rows.items() if k[0] != username}
        else:
            self.rows.pop((username, namespace), None)


def _store(tmp_path, mirror=None):
    st = SqliteStore(str(tmp_path / "hub.db"))
    st.settings_mirror = mirror
    return st


# ─────────────────────────── no mirror: unchanged ───────────────────────────
def test_without_mirror_local_only(tmp_path):
    st = _store(tmp_path)
    st.set_user_settings("owner", "settings-center", {"risk": 2})
    assert st.get_user_settings("owner", "settings-center") == {"risk": 2}


# ─────────────────────────── mirror write-through ───────────────────────────
def test_set_writes_through_to_mirror(tmp_path):
    m = FakeMirror()
    st = _store(tmp_path, m)
    st.set_user_settings("owner", "dashboard", {"chartTf": "4h"})
    assert m.get("owner", "dashboard") == {"chartTf": "4h"}          # durable copy exists


# ─────────────────────────── the actual bug: survive a restart ───────────────────────────
def test_settings_survive_ephemeral_restart(tmp_path):
    m = FakeMirror()
    # session 1 saves settings
    st1 = _store(tmp_path / "a", m)
    st1.set_user_settings("owner", "settings-center", {"strategy": "SMC", "risk": 1.5})

    # restart: the local SQLite disk is GONE (fresh path), but the mirror persists
    st2 = _store(tmp_path / "b", m)
    got = st2.get_user_settings("owner", "settings-center")
    assert got == {"strategy": "SMC", "risk": 1.5}                    # restored, not defaults!
    # and it backfilled the fresh local cache
    assert st2._sqlite_get_settings("owner", "settings-center") == {"strategy": "SMC", "risk": 1.5}


def test_local_cache_preferred_over_mirror(tmp_path):
    m = FakeMirror()
    st = _store(tmp_path, m)
    st.set_user_settings("owner", "dashboard", {"v": 1})
    m.rows[("owner", "dashboard")] = {"v": 999}      # mirror drifts (shouldn't be read on a hit)
    assert st.get_user_settings("owner", "dashboard") == {"v": 1}     # local cache wins


def test_delete_clears_both(tmp_path):
    m = FakeMirror()
    st = _store(tmp_path, m)
    st.set_user_settings("owner", "dashboard", {"v": 1})
    st.delete_user_settings("owner", "dashboard")
    assert st.get_user_settings("owner", "dashboard") == {}
    assert m.get("owner", "dashboard") is None


def test_runtime_overrides_survive_redeploy_via_mirror(tmp_path):
    """The REAL settings path (save/load_overrides) must mirror to Supabase and
    restore after an ephemeral-disk wipe — the bug where settings reset on every
    login because the mirror was never wired to this path."""
    import services.runtime_settings as rs

    class FakeMirror:
        def __init__(self): self.db = {}
        def get(self, u, ns): return self.db.get((u, ns))
        def set(self, u, ns, data): self.db[(u, ns)] = dict(data)

    orig = rs._mirror_cache
    rs._mirror_cache = {"built": True, "store": FakeMirror()}
    try:
        path = str(tmp_path / "settings.json")
        rs.save_overrides(path, {"auto_strategy": "smc", "risk_per_trade_pct": 0.02})
        import os
        os.remove(path)                                  # simulate ephemeral redeploy
        loaded = rs.load_overrides(path)
        assert loaded["auto_strategy"] == "smc"
        assert loaded["risk_per_trade_pct"] == 0.02
        assert os.path.exists(path)                      # local cache re-warmed
    finally:
        rs._mirror_cache = orig
