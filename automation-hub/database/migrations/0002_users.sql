-- Phase 7: user accounts with hashed passwords (PBKDF2). Replaces the single
-- config-based operator. The default admin is seeded from HUB_USERNAME /
-- HUB_PASSWORD on first run.

CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'operator',
    created_at    TEXT NOT NULL
);
