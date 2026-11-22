-- Grupos desactivados: se conservan con sus miembros, su rol, su cuota y su acceso a carpetas, pero no dan nada
-- mientras lo estén (core/groups.refresh_user los quita de la lista efectiva users.groups). El de serie «admins»,
-- siempre activo.
ALTER TABLE groups ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1;
