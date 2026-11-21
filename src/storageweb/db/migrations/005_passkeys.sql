-- 005: passkeys (WebAuthn) como segundo paso, junto al TOTP de mfa_factors (core/mfa/webauthn.py).
--
-- Una cuenta puede tener varias (el portátil con Windows Hello, el móvil, una llave de seguridad), cada una con su
-- nombre. Las claves son públicas: no se cifran.
-- * credential_id: el id de la credencial (base64url), único en todo el servidor.
-- * public_key: la clave COSE tal como llegó (base64url de su CBOR); la vuelve a leer el mismo decodificador.
-- * alg: el algoritmo, fijado AL REGISTRAR (ES256, EdDSA o RS256): una aserción no elige con qué se comprueba.
-- * sign_count: el último contador de firmas visto; si deja de avanzar, la credencial se ha clonado.
CREATE TABLE mfa_passkeys (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id TEXT NOT NULL UNIQUE,
    public_key    TEXT NOT NULL,
    alg           INTEGER NOT NULL,
    sign_count    INTEGER NOT NULL DEFAULT 0,
    name          TEXT NOT NULL DEFAULT '',
    aaguid        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    last_used_at  TEXT
);
CREATE INDEX idx_mfa_passkeys_user ON mfa_passkeys(user_id);
