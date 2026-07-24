"""CI gate for the Postgres/Supabase identity migrations.

Static checks over ../migrations/*.sql (no live Postgres): every tenant-scoped
table must ship with RLS ENABLE+FORCE and an isolation policy — the standing
mitigation for DSP risk R4 ("RLS misconfig leaks tenant data")."""
from data import pg_migrations as pgm


def test_migrations_discovered_and_ordered():
    ms = pgm.discover()
    assert ms, "no Postgres migrations found"
    versions = [m.version for m in ms]
    assert versions == sorted(versions), "migrations must apply in filename order"
    assert len(versions) == len(set(versions)), "duplicate migration versions"
    assert versions[0].startswith("0001")


def test_identity_tables_present():
    sql = pgm.combined_sql().lower()
    for t in ("tenants", "users", "profiles", "sessions", "user_settings"):
        assert f"create table if not exists {t}" in sql, f"{t} table missing"


def test_every_tenant_table_has_rls_enabled_forced_and_policy():
    """The core gate: no tenant table may ship without full RLS."""
    cov = pgm.rls_coverage()
    assert set(cov) == set(pgm.TENANT_TABLES)
    for table, c in cov.items():
        assert c["created"], f"{table} is not created"
        assert c["enabled"], f"{table} missing ENABLE ROW LEVEL SECURITY"
        assert c["forced"], f"{table} missing FORCE ROW LEVEL SECURITY"
        assert c["policy"], f"{table} missing a tenant-isolation policy"


def test_tables_are_tenant_scoped_and_isolate_on_the_request_guc():
    sql = pgm.combined_sql().lower()
    # child tables reference the tenants table (FK) …
    for _ in ("users", "profiles", "sessions", "user_settings"):
        assert "references tenants(id)" in sql
    # … and policies isolate on the per-request GUC, default-deny when unset.
    assert "current_setting('app.current_tenant', true)" in sql


def test_owner_tenant_seeded_to_match_single_owner_runtime():
    # slug must equal services.tenancy.OWNER_TENANT so today's single-owner app
    # maps onto the schema with no behavior change.
    from services.tenancy import OWNER_TENANT
    sql = pgm.combined_sql()
    assert f"'{OWNER_TENANT}'" in sql
    assert "insert into tenants" in sql.lower()
