-- 003: tema visual preferido de cada usuario (system | light | dark; NULL = system)
ALTER TABLE users ADD COLUMN theme TEXT;
