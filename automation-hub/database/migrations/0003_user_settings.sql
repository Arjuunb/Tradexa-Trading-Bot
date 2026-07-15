-- Per-user persistent workspace settings. One row per (user, namespace) so a
-- user's Settings Center prefs, dashboard layout state, etc. survive logout,
-- refresh and re-login. Strictly isolated by username.
CREATE TABLE IF NOT EXISTS user_settings (
    username    TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '{}',
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (username, namespace)
);
