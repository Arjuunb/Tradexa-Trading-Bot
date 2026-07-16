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
-- H-5: paper_trades is scanned ~10x per signal (PnL / streak / Kelly / curve);
-- index the columns those queries filter/order on.
CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_opened ON paper_trades(opened_at);

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

-- ---------------------------------------------------------------------------
-- Permanent Trading Memory (optional Postgres mirror of the SQLite primary).
-- The bot's long-term memory of every trade — one row per closed trade,
-- composed from REAL captured data. Primary storage is SQLite under
-- HUB_DATA_DIR; these tables let you mirror the memory into Supabase/Postgres
-- for durable, queryable history. Uncaptured fields are stored as honest
-- markers in the JSON payload, never fabricated.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_memories (
    trade_id     TEXT PRIMARY KEY,
    created_at   TEXT,
    closed_at    TEXT,
    mode         TEXT,
    symbol       TEXT,
    side         TEXT,
    strategy     TEXT,
    timeframe    TEXT,
    entry        REAL,
    exit         REAL,
    stop         REAL,
    target       REAL,
    size         REAL,
    risk_amount  REAL,
    planned_rr   REAL,
    actual_rr    REAL,
    pnl          REAL,
    result       TEXT,                 -- win | loss | breakeven
    grade        TEXT,                 -- A..F process+outcome grade
    confidence   REAL,
    brain_score  REAL,
    regime       TEXT,
    session      TEXT,                 -- Tokyo | London | New York | ...
    weekday      TEXT,
    duration_s   REAL,
    sections     TEXT,                 -- JSON: the 8 memory categories
    features     TEXT,                 -- JSON: numeric feature vector (similarity)
    notes        TEXT,                 -- manual emotion/journal note
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_trade_memories_symbol  ON trade_memories(symbol);
CREATE INDEX IF NOT EXISTS ix_trade_memories_result  ON trade_memories(result);
CREATE INDEX IF NOT EXISTS ix_trade_memories_session ON trade_memories(session);
CREATE INDEX IF NOT EXISTS ix_trade_memories_closed  ON trade_memories(closed_at);

-- ---------------------------------------------------------------------------
-- Durable per-user settings (Supabase mirror of the SQLite user_settings table).
-- Lets saved settings / dashboard prefs survive a redeploy on the free tier, so
-- logging in restores real settings instead of defaults. Mirrored by
-- data/settings_store.py; SQLite under HUB_DATA_DIR stays the fast local cache.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_settings (
    username    TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    data        TEXT NOT NULL,
    updated_at  TEXT,
    PRIMARY KEY (username, namespace)
);

CREATE TABLE IF NOT EXISTS memory_reviews (
    id          SERIAL PRIMARY KEY,
    period      TEXT NOT NULL,         -- nightly | weekly | monthly | yearly
    period_key  TEXT NOT NULL,         -- 2026-07-12 / 2026-W28 / 2026-07 / 2026
    created_at  TEXT,
    report      TEXT,                  -- JSON: pattern-recognition report
    UNIQUE(period, period_key)
);
