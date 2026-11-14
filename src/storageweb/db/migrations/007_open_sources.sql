-- foreign_keys: off
-- El origen de usuarios y grupos (users.source, groups.source) deja de estar limitado a 'local', 'pam'
-- y 'entra': los métodos de inicio de sesión se descubren solos (providers/<método>/) y uno nuevo no
-- debe necesitar una migración. SQLite no permite cambiar un CHECK: se reconstruyen las tablas.

CREATE TABLE users_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name    TEXT,
    email           TEXT,
    source          TEXT NOT NULL CHECK (source <> ''),
    role            TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    password_hash   TEXT,
    external_id     TEXT,
    groups          TEXT NOT NULL DEFAULT '',
    home_path       TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_login      TEXT,
    locale          TEXT,
    theme           TEXT,
    external_groups TEXT NOT NULL DEFAULT ''
);
INSERT INTO users_new (id, username, display_name, email, source, role, password_hash, external_id, groups,
                       home_path, enabled, created_at, last_login, locale, theme, external_groups)
    SELECT id, username, display_name, email, source, role, password_hash, external_id, groups,
           home_path, enabled, created_at, last_login, locale, theme, external_groups FROM users;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
CREATE UNIQUE INDEX idx_users_external ON users(source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE groups_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'local' CHECK (source <> ''),
    external_id TEXT,
    created_at  TEXT NOT NULL,
    builtin     INTEGER NOT NULL DEFAULT 0
);
INSERT INTO groups_new (id, name, label, description, source, external_id, created_at, builtin)
    SELECT id, name, label, description, source, external_id, created_at, builtin FROM groups;
DROP TABLE groups;
ALTER TABLE groups_new RENAME TO groups;
CREATE UNIQUE INDEX idx_groups_external ON groups(source, external_id) WHERE external_id IS NOT NULL;
