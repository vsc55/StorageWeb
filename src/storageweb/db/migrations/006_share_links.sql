-- 006: enlaces para compartir un archivo o una carpeta con gente de fuera (core/links.py, /s/<token>).
--
-- share_links: cada enlace de una persona (user_id) a root:/rel, como lo ve ella («home» = su carpeta personal).
-- El token solo se guarda como SHA-256 (token_hash, para encontrarlo) y cifrado con la clave de los secretos
-- (token_enc, para que su dueño pueda volver a copiar el enlace): con la base de datos sola no se abre ninguno.
-- mode: download (ver y descargar) o upload (buzón: solo subir, sin ver lo que hay). Sigue al archivo si se renombra
-- o se mueve desde StorageWeb y se borra con él (como los favoritos). Al abrirlo cuentan los permisos de AHORA de
-- quien lo creó: si los pierde o se desactiva su cuenta, el enlace deja de funcionar.
CREATE TABLE share_links (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash    TEXT NOT NULL UNIQUE,
    token_enc     TEXT NOT NULL,
    root          TEXT NOT NULL,
    rel           TEXT NOT NULL,
    is_dir        INTEGER NOT NULL DEFAULT 0,
    mode          TEXT NOT NULL CHECK (mode IN ('download', 'upload')),
    password_hash TEXT,
    expires_at    TEXT,
    max_downloads INTEGER,
    downloads     INTEGER NOT NULL DEFAULT 0,
    uploads       INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT
);
CREATE INDEX idx_share_links_user ON share_links(user_id);
CREATE INDEX idx_share_links_root ON share_links(root, rel);
