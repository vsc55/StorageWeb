-- foreign_keys: off
-- 007: roles propios (core/roles.py): conjuntos con nombre de permisos sobre archivos, que se asignan a personas
-- (users.role) y a grupos (groups.role: el rol que reciben sus miembros, sumado al suyo).
--
-- roles: los creados desde la web. Los de serie no están aquí: «admin» (todo, también la administración) y «user»
-- (sus permisos son el ajuste permissions.user). permissions = los permisos separados por comas (PERMISSIONS).
CREATE TABLE roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (key NOT IN ('admin', 'user') AND key <> ''),
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    permissions TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- El rol que da un grupo a sus miembros (NULL = ninguno). Nunca «admin»: eso lo da el rol de la persona o el mapeo
-- de roles de un método de inicio de sesión (core/groups.py lo comprueba)
ALTER TABLE groups ADD COLUMN role TEXT;

-- users.role ya no se limita a admin/user: puede ser la clave de un rol propio. SQLite no quita un CHECK: la tabla
-- se reconstruye igual (mismas columnas, mismo orden, mismos índices)
CREATE TABLE users_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT NOT NULL UNIQUE,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name    TEXT,
    email           TEXT,
    source          TEXT NOT NULL CHECK (source <> ''),
    external_id     TEXT,
    role            TEXT NOT NULL DEFAULT 'user' CHECK (role <> ''),
    password_hash   TEXT,
    external_groups TEXT NOT NULL DEFAULT '',
    groups          TEXT NOT NULL DEFAULT '',
    home_path       TEXT,
    quota_mb        INTEGER,
    enabled         INTEGER NOT NULL DEFAULT 1,
    disabled_reason TEXT,
    locale          TEXT,
    theme           TEXT,
    created_at      TEXT NOT NULL,
    last_login      TEXT
);
INSERT INTO users_new SELECT id, uid, username, display_name, email, source, external_id, role, password_hash,
                             external_groups, groups, home_path, quota_mb, enabled, disabled_reason, locale, theme,
                             created_at, last_login FROM users;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
CREATE UNIQUE INDEX idx_users_external ON users(source, external_id) WHERE external_id IS NOT NULL;
