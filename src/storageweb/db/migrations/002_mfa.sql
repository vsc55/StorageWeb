-- 002: verificación en dos pasos (TOTP).
--
-- mfa_factors: el segundo factor de una cuenta (uno por cuenta; hoy solo TOTP).
-- * secret: la semilla, cifrada con la clave de los secretos (enc:v1:, como los del resto de ajustes). Se vuelve a
--   cifrar al restaurar una copia de otro servidor y con rotate-secrets-key (secretbox.rekey).
-- * confirmed: 0 mientras el alta está a medias (aún no se ha comprobado un código de la aplicación). Un alta a
--   medias no es un factor: nada lo pide ni lo acepta.
-- * last_step: el último paso de 30 s aceptado (antirreplay): un código no vale dos veces.
CREATE TABLE mfa_factors (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    method     TEXT NOT NULL DEFAULT 'totp',
    secret     TEXT NOT NULL,
    confirmed  INTEGER NOT NULL DEFAULT 0,
    last_step  INTEGER NOT NULL DEFAULT -1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- mfa_recovery: los códigos de recuperación de una cuenta, de un solo uso. Solo su hash (como una contraseña); el
-- código en claro se enseña una sola vez, al generarlo.
CREATE TABLE mfa_recovery (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used_at   TEXT
);
CREATE INDEX idx_mfa_recovery_user ON mfa_recovery(user_id);
