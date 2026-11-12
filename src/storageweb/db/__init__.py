"""Persistencia en SQLite.

* ``connection``: conexión y migraciones versionadas (``migrations/*.sql``).
* ``repositories``: acceso a datos por entidad. Todas las funciones reciben la conexión como
  primer argumento, así que no dependen de Flask (la capa web gestiona una conexión por petición).
"""
from .connection import available_migrations, connect, init_db, migrate, now_iso, schema_version

__all__ = ["available_migrations", "connect", "init_db", "migrate", "now_iso", "schema_version"]
