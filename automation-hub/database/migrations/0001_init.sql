-- Phase 6: initial schema. Persists bot configs + last known state so the
-- Automation Hub survives a restart. Runtime metrics/trades stay in memory
-- (re-derived when a bot runs again).

CREATE TABLE IF NOT EXISTS bots (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    exchange      TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    mode          TEXT NOT NULL,
    risk_json     TEXT NOT NULL,
    starting_cash REAL NOT NULL,
    state         TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
