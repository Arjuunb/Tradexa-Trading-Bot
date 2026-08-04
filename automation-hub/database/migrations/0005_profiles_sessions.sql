-- 0005_profiles_sessions.sql — SaaS account surface: profiles, sessions, deletion
--
-- Three things the auth system had no place to put:
--
--   1. PROFILE fields. `users` held credentials and nothing a person would
--      recognise as their account — no display name, no avatar, no timezone,
--      no record of when they last signed in.
--
--   2. SESSIONS as rows. Sessions were a signed cookie and nothing else, which
--      is elegant until a user asks "what's logged into my account?" or
--      "sign out my old laptop". A stateless token cannot answer either
--      question, and cannot be revoked before it expires. Recording sessions
--      makes both possible; the cookie stays the credential, the row is what
--      the cookie is checked AGAINST.
--
--   3. DELETION. An account with no delete path is a GDPR problem and a support
--      burden. Soft-delete first (`deleted_at`) so an accidental deletion is
--      recoverable for a grace period, with a hard purge after.
--
-- Forward-only, additive, and safe on a populated database: every column is
-- nullable or defaulted, so existing rows stay valid and existing queries keep
-- working. SQLite's ALTER TABLE ADD COLUMN is O(1) and does not rewrite rows.

-- ── profile ──────────────────────────────────────────────────────────────────
ALTER TABLE users ADD COLUMN full_name TEXT;
ALTER TABLE users ADD COLUMN avatar_url TEXT;
-- IANA zone name ("Europe/London"), not an offset: offsets change twice a year
-- and a stored offset silently becomes wrong at the next DST boundary.
ALTER TABLE users ADD COLUMN timezone TEXT;
ALTER TABLE users ADD COLUMN last_login TEXT;
-- Free-form JSON. Deliberately opaque to the schema: preferences change far
-- more often than migrations should, and a column per toggle is a migration
-- per toggle.
ALTER TABLE users ADD COLUMN preferences TEXT;
-- Soft delete. NULL = active. Every user lookup filters on this, so a deleted
-- account cannot authenticate while its rows are still recoverable.
ALTER TABLE users ADD COLUMN deleted_at TEXT;

-- ── sessions ─────────────────────────────────────────────────────────────────
-- One row per signed-in device. The cookie carries the session id; this table
-- decides whether that id is still allowed to act.
CREATE TABLE IF NOT EXISTS user_sessions (
    id            TEXT PRIMARY KEY,      -- opaque session id, also in the cookie
    username      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    -- Truncated and stored for recognition only ("Chrome on macOS"), never for
    -- fingerprinting. A user identifying their own device is the whole point.
    user_agent    TEXT,
    ip            TEXT,
    -- Set when revoked, rather than deleting the row: "signed out from Berlin
    -- at 14:02" is an answer a security-conscious user wants, and a deleted row
    -- cannot give it.
    revoked_at    TEXT,
    revoked_by    TEXT,                  -- "user" | "admin" | "password_change"
    -- Whether "Remember me" was ticked. Drives the expiry that was chosen, and
    -- is shown in the session list so a long-lived session is visible as one.
    remembered    INTEGER NOT NULL DEFAULT 0
);

-- Listing a user's own sessions is the hot path (the account page), and
-- revocation sweeps filter the same way.
CREATE INDEX IF NOT EXISTS idx_user_sessions_username ON user_sessions(username);
-- Expiry sweeps scan on this.
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);
