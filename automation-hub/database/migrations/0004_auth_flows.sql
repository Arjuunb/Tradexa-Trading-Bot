-- Real auth flows: password reset, email verification, TOTP two-factor and
-- OAuth sign-in — all against the SAME users table the hub already authorises
-- against. One identity store; no second source of truth to drift.

-- An account's contact address, distinct from its login identity. Existing
-- rows signed up with an email AS the username, so backfill from it where it
-- looks like one; anything else stays NULL until the owner sets it.
ALTER TABLE users ADD COLUMN email TEXT;
ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN totp_secret TEXT;
ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN totp_last_step INTEGER;

UPDATE users SET email = username WHERE email IS NULL AND username LIKE '%_@_%.__%';

-- Single-use expiring tokens (password reset, email verification). Only the
-- SHA-256 of the token is stored: the plaintext is a temporary password, and
-- keeping it at rest would turn any read-only leak into account takeover.
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    purpose    TEXT NOT NULL,          -- 'reset' | 'verify'
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(username, purpose);

-- Recovery codes for a lost authenticator. Hash-only, single-use. Without
-- these, enabling 2FA is one dropped phone away from a permanent lockout.
CREATE TABLE IF NOT EXISTS totp_recovery (
    code_hash  TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_totp_recovery_user ON totp_recovery(username);

-- A federated identity linked to a local account. The provider's immutable
-- subject id is the key, never the email: emails get reassigned, and matching
-- on one lets a re-registered address inherit someone else's account.
CREATE TABLE IF NOT EXISTS oauth_identities (
    provider   TEXT NOT NULL,          -- 'google' | 'github'
    subject    TEXT NOT NULL,          -- provider's stable user id
    username   TEXT NOT NULL,
    email      TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider, subject)
);
CREATE INDEX IF NOT EXISTS idx_oauth_user ON oauth_identities(username);
