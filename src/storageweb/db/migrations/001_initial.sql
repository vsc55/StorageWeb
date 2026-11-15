-- 001: esquema de StorageWeb.
--
-- Las migraciones siguientes (002, 003…) solo añaden cambios sobre este esquema; una migración ya publicada no se
-- edita nunca (ver docs/arquitectura/decisiones/0007-migraciones.md).

-- --------------------------------------------------------------------------- cuentas

-- Usuarios de cualquier método de inicio de sesión (local, pam, entra… se descubren: ver providers/).
-- * uid: identificador público (UUID v4) de las direcciones y los formularios de la administración; id es la clave
--   interna de las relaciones y no sale nunca en una dirección.
-- * (source, external_id): la identidad en su proveedor (oid de Entra ID); el nombre puede cambiar (UPN nuevo).
-- * external_groups: los grupos tal como los da el proveedor (claims de Entra ID, grupos del sistema).
-- * groups: la lista efectiva (external_groups + nombres de sus grupos), la que usan las carpetas compartidas.
-- * quota_mb: cuota de su carpeta personal (NULL = la de sus grupos o la de por defecto; 0 = sin cuota).
-- * disabled_reason: NULL = desactivada a mano; 'directory' = la desactivó la revisión contra su proveedor (se
--   reactiva sola cuando el proveedor la vuelve a dejar entrar).
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT NOT NULL UNIQUE,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name    TEXT,
    email           TEXT,
    source          TEXT NOT NULL CHECK (source <> ''),
    external_id     TEXT,
    role            TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
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
CREATE UNIQUE INDEX idx_users_external ON users(source, external_id) WHERE external_id IS NOT NULL;

-- Grupos: locales (miembros a mano) o de un método que trae grupos (Entra ID con Object ID o App Role, PAM…).
-- * builtin = 1: el grupo de serie «admins» (no se edita ni se borra; sus miembros son los usuarios con rol admin,
--   que no se guardan en user_groups: el rol manda).
-- * home_quota_mb: cuota de la carpeta personal de sus miembros (NULL = el grupo no da cuota; 0 = sin cuota).
CREATE TABLE groups (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    label         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'local' CHECK (source <> ''),
    external_id   TEXT,
    builtin       INTEGER NOT NULL DEFAULT 0,
    home_quota_mb INTEGER,
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_groups_external ON groups(source, external_id) WHERE external_id IS NOT NULL;

-- Pertenencias: 'manual' (la pone un admin) o 'sync' (llega al iniciar sesión; solo esas se reemplazan).
CREATE TABLE user_groups (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    origin   TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual', 'sync')),
    added_at TEXT NOT NULL,
    PRIMARY KEY (user_id, group_id)
);
CREATE INDEX idx_user_groups_group ON user_groups(group_id);

INSERT INTO groups (uid, name, label, description, source, builtin, created_at)
VALUES (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-'
            || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))),
        'admins', 'Administrators', '', 'local', 1, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));

-- --------------------------------------------------------------------------- sesiones, tokens y bloqueos

-- Sesiones iniciadas. La cookie firmada lleva el id; si la fila no existe, la sesión está cerrada.
-- provider_sid: la sesión del proveedor SSO (claim «sid» de Entra ID): su cierre de sesión de canal frontal cierra
-- las sesiones de StorageWeb que la usan.
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_sid TEXT,
    created_at   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    ip           TEXT,
    user_agent   TEXT
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_provider_sid ON sessions(provider_sid);

-- Tokens de API personales («sw_…»): solo se guarda su hash SHA-256.
CREATE TABLE api_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    prefix       TEXT NOT NULL,
    scope        TEXT NOT NULL DEFAULT 'read' CHECK (scope IN ('read', 'write')),
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    last_ip      TEXT,
    expires_at   TEXT
);
CREATE INDEX idx_api_tokens_user ON api_tokens(user_id);

-- Reglas de IP: 'ban' (bloqueada) o 'allow' (nunca se bloquea). network = IP o red CIDR normalizada.
CREATE TABLE ip_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL CHECK (kind IN ('ban', 'allow')),
    network    TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    automatic  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    created_by TEXT,
    expires_at TEXT,
    UNIQUE (kind, network)
);

-- Infracciones recientes por IP (intentos fallidos, CSRF, tokens no válidos) para el bloqueo automático.
CREATE TABLE ip_offenses (
    ip   TEXT NOT NULL,
    ts   TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX idx_ip_offenses ON ip_offenses(ip, ts);

-- --------------------------------------------------------------------------- ajustes guardados desde la web

-- Un juego de ajustes por perfil (settings_profile en config.json; «default» si no). revision sube en cada
-- guardado y la caché de los ajustes efectivos la compara.
CREATE TABLE settings_profiles (
    name       TEXT PRIMARY KEY,
    revision   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    updated_by TEXT
);

-- Un campo de los ajustes (fields.py) con valor distinto del predeterminado en un perfil: la diferencia mínima.
-- Las listas y algunos diccionarios (role_mappings) son un único campo, como cuando se fijan en config.json.
CREATE TABLE settings_values (
    profile    TEXT NOT NULL,
    path       TEXT NOT NULL,              -- «auth.entra.client_secret», «storage.hidden»…
    value      TEXT NOT NULL,              -- JSON; los secretos, cifrados («enc:v1:…»)
    secret     INTEGER NOT NULL DEFAULT 0, -- 1 si lleva algún secreto cifrado
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (profile, path)
);

-- Carpetas compartidas creadas desde la web (las de config.json no están aquí: se leen de allí, de solo lectura).
CREATE TABLE shares (
    profile    TEXT NOT NULL,
    name       TEXT NOT NULL,
    label      TEXT NOT NULL,
    location   TEXT NOT NULL DEFAULT '',     -- '' = el disco del servidor; si no, el nombre de una ubicación
    path       TEXT NOT NULL,                -- ruta absoluta en el disco, o dentro de la ubicación
    read_only  INTEGER NOT NULL DEFAULT 0,
    quota_mb   INTEGER NOT NULL DEFAULT 0,   -- 0 = sin cuota
    position   INTEGER NOT NULL DEFAULT 0,   -- orden en la lista
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (profile, name)
);

-- Quién entra en cada carpeta: todos (kind = all, ref = '*'), un usuario o un grupo, con lectura o escritura.
CREATE TABLE share_access (
    profile TEXT NOT NULL,
    share   TEXT NOT NULL,
    kind    TEXT NOT NULL CHECK (kind IN ('all', 'user', 'group')),
    ref     TEXT NOT NULL,
    level   TEXT NOT NULL CHECK (level IN ('read', 'write')),
    PRIMARY KEY (profile, share, kind, ref),
    FOREIGN KEY (profile, share) REFERENCES shares(profile, name) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX idx_share_access_ref ON share_access(kind, ref);

-- Ubicaciones de almacenamiento externo (S3, SMB, SFTP…) creadas desde la web.
CREATE TABLE locations (
    profile    TEXT NOT NULL,
    name       TEXT NOT NULL,
    label      TEXT NOT NULL,
    type       TEXT NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (profile, name)
);

-- Opciones de cada ubicación: dependen de su tipo (las declara su backend), así que van como nombre → valor.
CREATE TABLE location_options (
    profile  TEXT NOT NULL,
    location TEXT NOT NULL,
    name     TEXT NOT NULL,
    value    TEXT NOT NULL,                  -- JSON de un valor simple; los secretos, cifrados («enc:v1:…»)
    secret   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile, location, name),
    FOREIGN KEY (profile, location) REFERENCES locations(profile, name) ON DELETE CASCADE ON UPDATE CASCADE
);

-- Estado interno como documentos JSON: cuándo corrió cada tarea de mantenimiento, permisos del último inicio de
-- sesión de cada método SSO…
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    revision   INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);

-- --------------------------------------------------------------------------- operación

-- Registro de eventos (docs/referencia/auditoria.md).
CREATE TABLE audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    username TEXT,
    action   TEXT NOT NULL,
    target   TEXT,
    ip       TEXT,
    detail   TEXT
);
CREATE INDEX idx_audit_ts ON audit_log(ts);

-- Subidas por partes en curso (el progreso real es el tamaño del fichero .part en disco).
CREATE TABLE uploads (
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
CREATE INDEX idx_uploads_updated ON uploads(updated_at);
