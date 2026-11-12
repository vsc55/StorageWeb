-- 004: grupos gestionados (locales, de Entra ID o del sistema) y pertenencias.
--
-- * groups.external_id: Object ID o App Role de Entra ID, o nombre del grupo del sistema (PAM).
-- * user_groups.origin: 'manual' (la pone un admin) o 'sync' (llega en el inicio de sesión).
--   Al sincronizar solo se reemplazan las 'sync'; las manuales se conservan.
-- * users.external_groups: grupos tal como los da el proveedor (claims de Entra ID o grupos PAM).
-- * users.groups sigue siendo la lista efectiva (external_groups + nombres de sus grupos), la que
--   usan las carpetas compartidas.

CREATE TABLE groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'local' CHECK (source IN ('local', 'entra', 'pam')),
    external_id TEXT,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_groups_external ON groups(source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE user_groups (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    origin   TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual', 'sync')),
    added_at TEXT NOT NULL,
    PRIMARY KEY (user_id, group_id)
);
CREATE INDEX idx_user_groups_group ON user_groups(group_id);

ALTER TABLE users ADD COLUMN external_groups TEXT NOT NULL DEFAULT '';

-- Los grupos de los usuarios de Entra ID y PAM venían del proveedor
UPDATE users SET external_groups = groups WHERE source IN ('entra', 'pam');

-- Los de los usuarios locales los puso un admin: pasan a ser grupos locales con pertenencia manual
WITH RECURSIVE split(uid, grp, rest) AS (
    SELECT id, '', groups || ',' FROM users WHERE source = 'local' AND groups <> ''
    UNION ALL
    SELECT uid, substr(rest, 1, instr(rest, ',') - 1), substr(rest, instr(rest, ',') + 1)
    FROM split WHERE rest <> ''
)
INSERT OR IGNORE INTO groups (name, label, source, created_at)
SELECT DISTINCT grp, grp, 'local', strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') FROM split WHERE grp <> '';

WITH RECURSIVE split(uid, grp, rest) AS (
    SELECT id, '', groups || ',' FROM users WHERE source = 'local' AND groups <> ''
    UNION ALL
    SELECT uid, substr(rest, 1, instr(rest, ',') - 1), substr(rest, instr(rest, ',') + 1)
    FROM split WHERE rest <> ''
)
INSERT OR IGNORE INTO user_groups (user_id, group_id, origin, added_at)
SELECT split.uid, groups.id, 'manual', strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
FROM split JOIN groups ON groups.name = split.grp WHERE split.grp <> '';
