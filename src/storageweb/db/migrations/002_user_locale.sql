-- 002: idioma preferido de cada usuario (NULL = el del navegador o default_locale)
ALTER TABLE users ADD COLUMN locale TEXT;
