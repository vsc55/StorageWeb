-- 008: trazabilidad de los enlaces para compartir (core/links.py).
--
-- Quitar un enlace ya no borra su fila: queda marcado (revoked_at, revoked_by y por qué: owner, admin o deleted
-- cuando se borró lo compartido) y deja de funcionar. La limpieza (tarea link_cleanup) borra los quitados o
-- caducados hace más de 30 días, pero no su historial.
ALTER TABLE share_links ADD COLUMN revoked_at TEXT;
ALTER TABLE share_links ADD COLUMN revoked_by TEXT;
ALTER TABLE share_links ADD COLUMN revoke_reason TEXT;

-- share_link_events: cada cosa que pasa con un enlace, con su fecha, la IP y el navegador. Sin clave ajena a
-- share_links a propósito: el historial se conserva aunque el enlace se borre (lleva su uid, su dueño y lo que
-- compartía en ese momento). event: created, opened, password_failed, unlocked, download, zip, upload, refused,
-- revoked. Se purga con la retención de la auditoría (maintenance.audit_retention_days).
CREATE TABLE share_link_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    link_uid    TEXT NOT NULL,
    owner       TEXT,
    target      TEXT,
    event       TEXT NOT NULL,
    path        TEXT,
    ip          TEXT,
    user_agent  TEXT,
    detail      TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX idx_share_link_events_link ON share_link_events(link_uid, at);
CREATE INDEX idx_share_link_events_at ON share_link_events(at);
