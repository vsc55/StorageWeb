"""Lo común de los almacenamientos de objetos (S3, Azure Blob): no hay carpetas de verdad, sino prefijos de nombre.
``informes/2026/`` existe si hay objetos debajo o un objeto marcador vacío con ese nombre (lo crea ``mkdir``);
renombrar es copiar y borrar objeto a objeto, así que con carpetas grandes tarda.

Aquí está todo lo que no depende del servicio. Cada uno (``s3.py``, ``azure.py``) pone sus llamadas
(``_read_from``, ``_put_empty``, ``_keys_under``, ``_move_object``, ``_delete_keys``, ``_upload``, ``_any_under``),
su ``stat``/``listdir`` y cómo traduce sus errores (``_fail``). No es un tipo de ubicación (sin ``schema``: el
descubrimiento de ``backends.discover`` la salta).
"""
from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .base import BackendError, Entry, RangedReader, RemoteBackend, clean_rel, join_rel


class ObjectStoreBackend(RemoteBackend):
    unlimited_space = True  # almacenamiento de objetos: sin tamaño fijo
    prefix = ""             # dónde va todo dentro del bucket o contenedor (relativo, sin barra al final)

    # ------------------------------------------------------------------ lo que pone cada servicio
    def _fail(self, exc: Exception) -> BackendError:
        """El error del servicio, como :class:`BackendError` con un mensaje para el usuario."""
        raise NotImplementedError

    def _read_from(self, key: str, pos: int):
        """Un flujo con el contenido de ``key`` desde el byte ``pos`` hasta el final."""
        raise NotImplementedError

    def _put_empty(self, key: str) -> None:
        """Un objeto vacío (el marcador de una carpeta: ``key`` acaba en ``/``)."""
        raise NotImplementedError

    def _keys_under(self, prefix: str) -> Iterable[str]:
        """Los nombres de todos los objetos que empiezan por ``prefix`` (a cualquier profundidad)."""
        raise NotImplementedError

    def _move_object(self, src: str, dst: str) -> None:
        raise NotImplementedError

    def _delete_keys(self, keys: list[str]) -> None:
        raise NotImplementedError

    def _upload(self, local: Path, key: str) -> None:
        raise NotImplementedError

    def _any_under(self, prefix: str) -> bool:
        """Si hay al menos un objeto que empieza por ``prefix`` (también sirve para comprobar el acceso)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ común
    @contextmanager
    def _service(self) -> Iterator[None]:
        """Las llamadas al servicio: cualquier error sale como :class:`BackendError` (``_fail``)."""
        try:
            yield
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from exc

    def _key(self, rel: str) -> str:
        return join_rel(self.prefix, clean_rel(rel))

    def _dir_prefix(self, rel: str) -> str:
        key = self._key(rel)
        return f"{key}/" if key else ""

    def open(self, rel: str):
        entry = self._file_entry(rel)
        key = self._key(rel)

        def fetch(pos: int):
            with self._service():
                return self._read_from(key, pos)
        return io.BufferedReader(RangedReader(fetch, entry.size), 1024 * 1024), entry.size, entry.mtime

    def mkdir(self, rel: str) -> None:
        if self.exists(rel):
            raise FileExistsError(rel)
        with self._service():
            self._put_empty(self._dir_prefix(rel))

    def _move(self, rel: str, new_rel: str, entry: Entry) -> None:
        with self._service():
            if entry.is_dir:
                old_prefix, new_prefix = self._dir_prefix(rel), self._dir_prefix(new_rel)
                for key in list(self._keys_under(old_prefix)):
                    self._move_object(key, new_prefix + key[len(old_prefix):])
            else:
                self._move_object(self._key(rel), self._key(new_rel))

    def delete(self, rel: str) -> None:
        entry = self._existing(rel)
        with self._service():
            keys = list(self._keys_under(self._dir_prefix(rel))) if entry.is_dir else [self._key(rel)]
            self._delete_keys(keys)

    def store(self, local: Path, rel: str) -> None:
        with self._service():
            self._upload(local, self._key(rel))
        local.unlink(missing_ok=True)

    def ensure_root(self, home: bool = False) -> None:
        if self.prefix and not self.root_exists():
            with self._service():
                self._put_empty(self._dir_prefix(""))

    def check(self) -> None:
        with self._service():
            self._any_under(self._dir_prefix(""))
