-- 005: grupos de serie. «admins» no se borra ni se edita; sus miembros son los usuarios con rol
-- admin (no se guardan en user_groups: el rol manda).
--
-- Si ya existía un grupo local llamado «admins» (p. ej. migrado desde users.groups), se renombra a
-- «admins-local» para conservar sus miembros; las carpetas que usaban «admins» pasan a referirse
-- a los administradores.

ALTER TABLE groups ADD COLUMN builtin INTEGER NOT NULL DEFAULT 0;

UPDATE groups SET name = 'admins-local', label = label || ' (local)' WHERE name = 'admins';

INSERT INTO groups (name, label, description, source, builtin, created_at)
VALUES ('admins', 'Administrators', '', 'local', 1, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));
