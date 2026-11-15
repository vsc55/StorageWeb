-- Sincronización con el directorio del proveedor (Entra ID).
-- Por qué se desactivó la cuenta: NULL = a mano (un admin); 'directory' = el proveedor la desactivó, la borró o
-- ya no la deja entrar. Las desactivadas por el directorio se reactivan solas cuando el proveedor vuelve a dejarla.
ALTER TABLE users ADD COLUMN disabled_reason TEXT;

-- Sesión del proveedor (claim «sid» de Entra ID) con la que se inició cada sesión: cerrar sesión en Microsoft
-- (cierre de sesión de canal frontal) cierra las sesiones de StorageWeb que la usan.
ALTER TABLE sessions ADD COLUMN provider_sid TEXT;
CREATE INDEX idx_sessions_provider_sid ON sessions(provider_sid);
