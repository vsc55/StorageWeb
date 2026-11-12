-- 001: esquema inicial de StorageWeb.
-- Usa IF NOT EXISTS para adoptar bases de datos creadas antes de las migraciones versionadas.

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT,
    email         TEXT,
    source        TEXT NOT NULL CHECK (source IN ('local', 'pam', 'entra')),
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    password_hash TEXT,
    external_id   TEXT,
    groups        TEXT NOT NULL DEFAULT '',
    home_path     TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_external
    ON users(source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    username TEXT,
    action   TEXT NOT NULL,
    target   TEXT,
    ip       TEXT,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

-- Ajustes editables desde la web (JSON) con revisión para invalidar cachés
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    revision   INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);

-- Subidas por partes en curso (el progreso real es el tamaño del fichero .part en disco)
CREATE TABLE IF NOT EXISTS uploads (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    root       TEXT NOT NULL,
    dir_rel    TEXT NOT NULL,
    dir_path   TEXT NOT NULL,
    filename   TEXT NOT NULL,
    size       INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uploads_updated ON uploads(updated_at);
