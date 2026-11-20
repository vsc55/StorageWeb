-- 003: favoritos del explorador y un índice para «Recientes».
--
-- favorites: carpetas o archivos que cada usuario marca con la estrella. root es el nombre de la carpeta de
-- StorageWeb («home» = la personal de ese usuario, o una compartida) y rel la ruta dentro de ella. Si se renombra,
-- mueve o borra algo desde StorageWeb (web o unidad de red), sus favoritos se actualizan (core/favorites.py).
CREATE TABLE favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    root       TEXT NOT NULL,
    rel        TEXT NOT NULL,
    is_dir     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, root, rel)
);
CREATE INDEX idx_favorites_root ON favorites(root, rel);

-- «Recientes» sale de la auditoría (lo último que cada usuario abrió, descargó o subió desde la web)
CREATE INDEX idx_audit_user_ts ON audit_log(username, ts);
