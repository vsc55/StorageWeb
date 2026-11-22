"""Ajustes efectivos por capas: predeterminados < web (SQLite) < config.json < entorno.

Los ajustes web se guardan por perfil y campo (``settings.store``: tabla ``settings_values``), como la
diferencia mínima con los valores predeterminados, y el perfil lleva un número de revisión. ``RuntimeSettings``
cachea la configuración combinada y solo la recalcula cuando cambia la revisión. No depende de Flask: recibe la
conexión en cada llamada.

Un campo presente en config.json o en una variable de entorno está **bloqueado** (:meth:`locked`):
la web no lo puede cambiar ni restablecer, y lo que hubiera guardado para él no se usa.
"""
from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path
from sqlite3 import Connection

from ..i18n import _
from .defaults import SECRET_FIELDS
from .env import env_name
from .errors import ConfigError
from .layers import (CONFIG_ORIGINS, _get, _set, diff_overrides, drop_path, leaf_paths, runtime_part, runtime_view,
                     without_origin)
from .loader import normalize
from . import secretbox, store

_MISSING = object()


def _is_entity(path: str) -> bool:
    return any(path == p or path.startswith(p + ".") for p in store.ENTITY_PATHS)


def _merge_entities(now: dict, wanted: dict, base: dict | None) -> dict:
    """Sobre lo guardado *ahora*, solo lo que quien guarda cambió respecto a lo que tenía en pantalla (``base``):
    carpetas y ubicaciones por nombre, cuotas por grupo. Así no se deshace lo que otro guardó entre medias."""
    out = copy.deepcopy(now)
    for key in ("shares", "locations"):
        if key not in wanted:
            continue
        mine = {i["name"]: i for i in wanted[key]}
        before = {i["name"]: i for i in (base or {}).get(key, [])}
        items = [i for i in out.get(key, [])]
        names = [i["name"] for i in items]
        for name in before.keys() - mine.keys():  # las que quitó
            if name in names:
                items = [i for i in items if i["name"] != name]
                names.remove(name)
        for name, item in mine.items():
            if before.get(name) == item:
                continue
            if name in names:
                items[names.index(name)] = item
            else:
                items.append(item)
                names.append(name)
        out[key] = items
    if "group_quotas" in wanted:
        quotas = dict(out.get("group_quotas", {}))
        before = (base or {}).get("group_quotas", {})
        for name in before.keys() | wanted["group_quotas"].keys():
            if wanted["group_quotas"].get(name) != before.get(name):
                if name in wanted["group_quotas"]:
                    quotas[name] = wanted["group_quotas"][name]
                else:
                    quotas.pop(name, None)
        out["group_quotas"] = quotas
    return out

ORIGINS = ("web", "file", "env")  # de dónde viene un valor que no es el predeterminado
_log = logging.getLogger(__name__)


class RuntimeSettings:
    def __init__(self, file_cfg: dict, cfg_path: Path, env_cfg: dict | None = None, profile: str = "default"):
        self.file_cfg = file_cfg
        self.cfg_path = cfg_path
        self.env_cfg = env_cfg or {}
        self.profile = profile
        self.labeler = lambda path: path  # la web lo sustituye por la etiqueta visible del campo
        # Clave de los secretos guardados (``secretbox``): con ella se cifran al guardar y se descifran al leer.
        # Sin clave (pruebas, herramientas) se guardan tal cual.
        self.secrets_key: bytes | None = None
        self._lock = threading.Lock()
        self._rev: int | None = None
        self._cfg: dict | None = None
        self._defaults: dict | None = None
        self._locked: dict[str, str] | None = None

    def _normalize(self, overrides: dict | None = None) -> dict:
        return normalize(self.file_cfg, self.cfg_path, overrides, self.env_cfg)

    # ------------------------------------------------------------------ capas

    def defaults(self) -> dict:
        """Secciones editables con sus valores predeterminados (rutas ya resueltas)."""
        if self._defaults is None:
            self._defaults = runtime_view(normalize({}, self.cfg_path))
        return self._defaults

    def locked(self) -> dict[str, str]:
        """Campos fijados fuera de la web: ``{ruta: "file" | "env"}`` (el entorno gana). Las carpetas, ubicaciones y
        cuotas de grupo no cuentan: se bloquea cada una, no la lista (su ``origin``; ver :meth:`config_entities`)."""
        if self._locked is None:
            found = {p: "file" for p in leaf_paths(runtime_part(self.file_cfg))}
            found.update({p: "env" for p in leaf_paths(runtime_part(self.env_cfg))})
            self._locked = {p: o for p, o in found.items() if not _is_entity(p)}
        return self._locked

    def lock_of(self, dotted: str) -> str | None:
        """``"file"``/``"env"`` si el campo (o la lista o el diccionario que lo contiene) está bloqueado."""
        for path, source in self.locked().items():
            if dotted == path or dotted.startswith(path + ".") or path.startswith(dotted + "."):
                return source
        return None

    def lock_message(self, dotted: str) -> str:
        name = self.labeler(dotted)
        if self.lock_of(dotted) == "env":
            return _("«%(path)s» is set by the environment variable %(name)s and cannot be changed from the web.",
                     path=name, name=env_name(dotted))
        return _("«%(path)s» is set in config.json and cannot be changed from the web.", path=name)

    def lock_notice(self, dotted: str) -> str:
        """El mensaje de bloqueo si el campo está bloqueado; vacío si se puede cambiar."""
        return self.lock_message(dotted) if self.lock_of(dotted) else ""

    def modified_paths(self, conn: Connection) -> set[str]:
        """Campos cuyo valor efectivo no es el predeterminado (las entidades tienen sus propias páginas)."""
        return {p for p in leaf_paths(diff_overrides(self.defaults(), runtime_view(self.current(conn))))
                if not _is_entity(p)}

    def config_entities(self) -> dict:
        """Lo fijado en config.json o el entorno de cada entidad: ``{"shares": {nombre}, "locations": {nombre},
        "group_quotas": {grupo}}``. Esas no se pueden cambiar desde la web."""
        found = {"shares": set(), "locations": set(), "group_quotas": set()}
        for doc in (self.file_cfg, self.env_cfg):
            storage = (doc or {}).get("storage") or {}
            for key in ("shares", "locations"):
                if isinstance(storage.get(key), list):
                    found[key] = {str(i.get("name", "")).strip() for i in storage[key] if isinstance(i, dict)}
            if isinstance(storage.get("group_quotas"), dict):
                found["group_quotas"] |= {str(k).strip().lower() for k in storage["group_quotas"]}
        return found

    def origins(self, conn: Connection) -> dict[str, str]:
        """Origen de cada campo que no sale de los predeterminados: ``web``, ``file`` o ``env``.

        Los bloqueados aparecen siempre, aunque su valor coincida con el predeterminado.
        """
        result = {p: "web" for p in self.modified_paths(conn)}
        for path in list(result):
            source = self.lock_of(path)
            if source:
                result[path] = source
        result.update(self.locked())
        return result

    # ------------------------------------------------------------------ lectura

    def current(self, conn: Connection) -> dict:
        rev = (store.revision(conn, self.profile), store.roles_revision(conn))
        with self._lock:
            if self._rev != rev:
                overrides = self._with_entities(self.overrides(conn), self.entities(conn))
                try:
                    cfg = self._normalize(overrides)
                except ConfigError:
                    _log.exception("Ajustes web no válidos; se usan solo config.json y el entorno")
                    cfg = self._normalize()
                # Los roles propios y los de los grupos (no son ajustes: core/roles.py), para calcular permisos
                self._cfg = {**cfg, **store.read_roles(conn)}
                self._rev = rev
            return self._cfg

    def overrides(self, conn: Connection) -> dict:
        """Los ajustes web guardados del perfil, con los secretos ya descifrados (las entidades van aparte)."""
        return secretbox.decrypt_doc(self.secrets_key, store.read_doc(conn, self.profile), lenient=True)

    def entities(self, conn: Connection) -> dict:
        """Carpetas, ubicaciones y cuotas de grupo guardadas desde la web (los secretos, descifrados)."""
        found = store.read_entities(conn, self.profile)
        opened = secretbox.decrypt_doc(self.secrets_key, {"storage": {"locations": found["locations"]}}, lenient=True)
        found["locations"] = opened["storage"]["locations"]
        return found

    def _with_entities(self, overrides: dict, entities: dict) -> dict:
        out = copy.deepcopy(overrides)
        out.setdefault("storage", {}).update(entities)
        return out

    def info(self, conn: Connection):
        """Último cambio del perfil (``updated_at``, ``updated_by``) o ``None``."""
        return store.info(conn, self.profile)

    def changes(self, conn: Connection) -> dict[str, dict]:
        """Quién y cuándo cambió cada campo guardado desde la web: ``{ruta: {"by", "at"}}``."""
        return store.changes(conn, self.profile)

    def validate(self, runtime: dict) -> dict:
        return self._normalize(runtime)

    def _minimal(self, full: dict) -> dict:
        """Lo que se guarda como ajustes: la diferencia con los predeterminados, sin lo bloqueado ni las entidades."""
        minimal = diff_overrides(self.defaults(), runtime_view(full))
        for path in [*self.locked(), *store.ENTITY_PATHS]:
            minimal = drop_path(minimal, path)
        return minimal

    def _web_entities(self, view: dict) -> dict:
        """Las entidades de la web dentro de una vista de los ajustes (sin las de config.json ni el entorno)."""
        storage = view.get("storage") or {}
        config = self.config_entities()
        out = {}
        for key in ("shares", "locations"):
            if key in storage:
                out[key] = [without_origin(item) for item in storage[key]
                            if isinstance(item, dict) and item.get("origin") not in CONFIG_ORIGINS]
        if "group_quotas" in storage:
            out["group_quotas"] = {k: v for k, v in (storage["group_quotas"] or {}).items()
                                   if k not in config["group_quotas"]}
        return out

    def _check_entities(self, conn: Connection, runtime: dict) -> None:
        """Lo de config.json o el entorno no se cambia desde la web, y una nueva no puede llamarse igual."""
        effective = self.current(conn)["storage"]
        storage = runtime.get("storage") or {}
        for key, label in (("shares", "storage.shares"), ("locations", "storage.locations")):
            if key not in storage:
                continue
            wanted = {i.get("name"): i for i in storage[key] if isinstance(i, dict)}
            for item in effective[key]:
                if item.get("origin") not in CONFIG_ORIGINS:
                    continue
                mine = wanted.get(item["name"])
                if mine is None or without_origin(mine) != without_origin(item):
                    raise ConfigError(self._entity_lock_message(key, item["name"], item["origin"]), label)
                if mine.get("origin") not in CONFIG_ORIGINS:
                    raise ConfigError(_("There is already one named %(name)s in config.json.", name=repr(item["name"])),
                                      label)
        if "group_quotas" in storage:
            current = effective["group_quotas"]
            for name in self.config_entities()["group_quotas"]:
                if storage["group_quotas"].get(name) != current.get(name):
                    raise ConfigError(_("The quota of the group %(name)s is set in config.json or the environment and "
                                        "cannot be changed from the web.", name=repr(name)), "storage.group_quotas")

    def _entity_lock_message(self, key: str, name: str, origin: str) -> str:
        what = _("The shared folder %(name)s", name=repr(name)) if key == "shares" else \
            _("The storage location %(name)s", name=repr(name))
        if origin == "env":
            return _("%(what)s is set by an environment variable and cannot be changed from the web.", what=what)
        return _("%(what)s is set in config.json and cannot be changed from the web.", what=what)

    # ------------------------------------------------------------------ escritura

    def save(self, conn: Connection, runtime: dict, username: str | None, strict: bool = False,
             base: dict | None = None) -> dict:
        """Valida y guarda los ajustes editables. Lanza ConfigError si no son válidos.

        Los campos bloqueados no se guardan. Con ``strict`` (cambios que no vienen de un formulario
        completo: matriz, carpetas, logo, Entra ID…) intentar cambiar uno es un error.

        ``base`` es la vista de la que partió quien llama (lo que había en pantalla, normalmente
        ``runtime_view(settings())``): entonces solo se guardan los campos en los que ``runtime`` difiere de
        ``base``, sobre lo que haya guardado *ahora*, en una transacción. Así dos admins que guardan cosas
        distintas a la vez no se pisan. Sin ``base``, el perfil queda exactamente como ``runtime``.
        Solo se escriben las filas que cambian: cada campo conserva quién y cuándo lo cambió.
        """
        runtime = copy.deepcopy(runtime)
        previous = self.overrides(conn)
        for path in SECRET_FIELDS:
            if path[0] in runtime and not _get(runtime, path) and _get(previous, path):
                _set(runtime, path, _get(previous, path))  # vacío = conservar el anterior
        if strict:
            effective = runtime_view(self.current(conn))
            for path in self.locked():
                keys = tuple(path.split("."))
                if _get(runtime, keys) != _get(effective, keys):
                    raise ConfigError(self.lock_message(path), path)
        self._check_entities(conn, runtime)
        wanted = store.flatten(self._minimal(self.validate(runtime)))
        before = store.flatten(self._minimal(self.validate(base))) if base is not None else None
        want_entities = self._web_entities(runtime)
        base_entities = self._web_entities(base) if base is not None else None

        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")  # nadie más escribe ajustes entre leer y guardar
        try:
            raw = store.read_doc(conn, self.profile)
            current = store.flatten(secretbox.decrypt_doc(self.secrets_key, raw, lenient=True))
            entities_now = self.entities(conn)
            if before is None:
                target = wanted
                target_entities = {**entities_now, **want_entities}
            else:
                touched = {p for p in wanted.keys() | before.keys() if wanted.get(p, _MISSING) != before.get(p, _MISSING)}
                target = dict(current)
                for path in touched:
                    if path in wanted:
                        target[path] = wanted[path]
                    else:
                        target.pop(path, None)
                target_entities = _merge_entities(entities_now, want_entities, base_entities)
                if touched:
                    target = store.flatten(self._minimal(self.validate(store.unflatten(target))))
            if target_entities != entities_now:  # lo de otros más lo mío: se valida el conjunto
                self.validate(self._with_entities(store.unflatten(target), target_entities))
            self._write(conn, raw, current, target, username)
            store.apply_entities(conn, self.profile, entities_now, target_entities, username, encode=self._seal_entity)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return store.unflatten(target)  # los ajustes guardados (las entidades van a sus tablas)

    def _write(self, conn: Connection, raw: dict, current: dict, target: dict, username: str | None) -> None:
        """Escribe ``target`` (en claro) sobre lo guardado: cifra solo los campos que cambian; los demás se quedan
        como están, con su autor y su fecha."""
        out = store.flatten(raw)
        for path in current.keys() | target.keys():
            new = target.get(path, _MISSING)
            if new == current.get(path, _MISSING):
                continue
            if new is _MISSING:
                out.pop(path, None)
            elif self.secrets_key is not None:
                out[path] = store.flatten(secretbox.encrypt_doc(self.secrets_key, store.unflatten({path: new})))[path]
            else:
                out[path] = new
        store.put_doc(conn, self.profile, store.unflatten(out), username, commit=False)

    def _seal_entity(self, key: str, item: dict) -> dict:
        """Una ubicación se guarda con sus secretos cifrados."""
        if key != "locations" or self.secrets_key is None:
            return item
        return secretbox.encrypt_doc(self.secrets_key, {"storage": {"locations": [item]}})["storage"]["locations"][0]

    def reset_path(self, conn: Connection, dotted: str, username: str | None) -> None:
        """Vuelve un ajuste a su valor predeterminado."""
        if self.lock_of(dotted):
            raise ConfigError(self.lock_message(dotted), dotted)
        remaining = drop_path(self.overrides(conn), dotted)
        self.validate(remaining)
        raw = store.flatten(store.read_doc(conn, self.profile))
        kept = {p: v for p, v in raw.items() if not (p == dotted or p.startswith(dotted + "."))}
        store.put_doc(conn, self.profile, store.unflatten(kept), username)

    def reset(self, conn: Connection, username: str | None) -> None:
        """Descarta todos los ajustes web: vuelven los predeterminados (salvo lo bloqueado)."""
        store.put_doc(conn, self.profile, {}, username)


def open_runtime(config_path=None, *, create_key: bool = True) -> tuple[RuntimeSettings, dict]:
    """Los ajustes por capas como los usa el servidor: ``(RuntimeSettings, configuración de arranque)``. La
    configuración de arranque es config.json + entorno (con sus secretos cifrados ya descifrados); los ajustes
    efectivos, con lo guardado desde la web, salen de ``RuntimeSettings.current(conn)`` (p. ej. en la CLI)."""
    from .loader import decrypted_layers  # noqa: PLC0415
    file_cfg, cfg_path, env_cfg, key = decrypted_layers(config_path, create_key=create_key, always_key=True)
    cfg = normalize(file_cfg, cfg_path, env_cfg=env_cfg)
    runtime = RuntimeSettings(file_cfg, cfg_path, env_cfg, cfg["settings_profile"])
    runtime.secrets_key = key
    return runtime, cfg
