-- Cuota de espacio de la carpeta personal de cada usuario, en MB.
-- NULL = la de por defecto (storage.home_quota_mb); 0 = sin cuota; > 0 = ese límite.
ALTER TABLE users ADD COLUMN quota_mb INTEGER;
