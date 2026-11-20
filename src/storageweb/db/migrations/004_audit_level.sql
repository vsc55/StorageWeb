-- 004: nivel de cada evento de la auditoría (storageweb/audit_levels.py): debug, info, warning, error o critical.
--
-- Los eventos que ya había toman el nivel de su acción (los mismos grupos que audit_levels.py); el resto, info.
ALTER TABLE audit_log ADD COLUMN level TEXT NOT NULL DEFAULT 'info';

UPDATE audit_log SET level = 'critical'
 WHERE action IN ('login_blocked', 'ip_banned', 'backup_restored', 'restore', 'settings_reset', 'secrets_key_rotated',
                  'mfa_reset_by_admin', 'user_deleted', 'audit_purged');
UPDATE audit_log SET level = 'error' WHERE action IN ('backup_failed', 'backup_offsite_failed');
UPDATE audit_log SET level = 'warning'
 WHERE action IN ('login_failed', 'mfa_failed', 'login_denied', 'password_change_failed', 'user_rename_failed',
                  'entra_app_register_failed', 'mfa_disabled')
    OR (action IN ('location_tested', 'audit_forward_test') AND COALESCE(detail, '') NOT LIKE 'ok%');
UPDATE audit_log SET level = 'debug' WHERE action = 'download' AND detail LIKE 'view%';

-- La página de auditoría filtra por nivel (de uno hacia arriba) y ordena por id
CREATE INDEX idx_audit_level ON audit_log(level, id);
