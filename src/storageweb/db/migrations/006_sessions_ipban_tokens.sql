-- 006: sesiones en el servidor, bloqueo de IPs y tokens de API.

-- Sesiones iniciadas. La cookie firmada lleva el id; si la fila no existe, la sesión está cerrada.
CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    ip         TEXT,
    user_agent TEXT
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

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

-- Infracciones recientes por IP (intentos fallidos, CSRF, tokens no válidos) para el bloqueo automático
CREATE TABLE ip_offenses (
    ip   TEXT NOT NULL,
    ts   TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX idx_ip_offenses ON ip_offenses(ip, ts);

-- Tokens de API personales. Solo se guarda el SHA-256 del token; prefix sirve para reconocerlo.
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
