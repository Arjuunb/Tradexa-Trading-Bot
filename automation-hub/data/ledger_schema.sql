-- Kyros / Automation Hub — Phase 1 ledger schema.
-- The same DDL backs the local SQLite ledger (dev) and Supabase/Postgres (prod).
-- Supabase becomes the source of truth; SQLite is the offline/dev fallback.

CREATE TABLE IF NOT EXISTS webhook_events (
    id           TEXT PRIMARY KEY,
    alert_id     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL,
    entry        REAL,
    stop         REAL,
    payload_json TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    status       TEXT NOT NULL,        -- accepted | rejected | duplicate
    reason       TEXT
);
CREATE INDEX IF NOT EXISTS idx_webhook_alert ON webhook_events(alert_id);

CREATE TABLE IF NOT EXISTS positions (
    id         TEXT PRIMARY KEY,
    symbol     TEXT NOT NULL,
    side       TEXT NOT NULL,
    size       REAL NOT NULL,
    entry      REAL NOT NULL,
    stop       REAL,
    status     TEXT NOT NULL,          -- open | closed
    pnl        REAL DEFAULT 0,
    opened_at  TEXT NOT NULL,
    closed_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);

CREATE TABLE IF NOT EXISTS paper_trades (
    id         TEXT PRIMARY KEY,
    alert_id   TEXT,
    symbol     TEXT NOT NULL,
    side       TEXT NOT NULL,
    size       REAL NOT NULL,
    entry      REAL NOT NULL,
    stop       REAL,
    exit       REAL,
    pnl        REAL,
    rr         REAL,
    status     TEXT NOT NULL,          -- open | closed
    source     TEXT NOT NULL DEFAULT 'paper',   -- paper | backtest | live (dataset separation)
    opened_at  TEXT NOT NULL,
    closed_at  TEXT
);

CREATE TABLE IF NOT EXISTS bot_logs (
    id       TEXT PRIMARY KEY,
    ts       TEXT NOT NULL,
    symbol   TEXT,
    level    TEXT NOT NULL,            -- info | warning | error
    stage    TEXT,                     -- webhook | dedup | risk | sizing | execution
    message  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id       TEXT PRIMARY KEY,
    ts       TEXT NOT NULL,
    severity TEXT NOT NULL,            -- info | warning | critical
    category TEXT NOT NULL,            -- risk | trade | system
    title    TEXT NOT NULL,
    detail   TEXT,
    read     INTEGER NOT NULL DEFAULT 0
);
