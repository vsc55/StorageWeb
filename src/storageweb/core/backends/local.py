"""Almacenamiento en el disco del servidor (también lo montado en él: NFS, SMB/CIFS, rclone…)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..security import UPLOAD_TMP_PREFIX, resolve_entry, resolve_inside
from .base import Backend, Entry, clean_rel, name_of, parent_rel


class LocalBackend(Backend):
    kind = "local"

    def __init__(self, base: Path, staging: Path):
        super().__init__(staging)
        self.base = Path(base)

    def describe(self) -> str:
        return str(self.base)

    def _path(self, rel: str) -> Path:
        return resolve_inside(self.base, clean_rel(rel))  # sigue symlinks pero sin salir de la raíz

    def local_path(self, rel: str) -> Path | None:
        return self._path(rel)

    def stat(self, rel: str) -> Entry | None:
        path = self._path(rel)
        try:
            st = path.stat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        return Entry(path.name, path.is_dir(), 0 if path.is_dir() else st.st_size, st.st_mtime)

    def listdir(self, rel: str) -> list[Entry]:
        entries = []
        with os.scandir(self._path(rel)) as it:
            for item in it:
                if item.name.startswith(UPLOAD_TMP_PREFIX):
                    continue
                try:
                    is_dir = item.is_dir()
                    st = item.stat()
                except OSError:
                    continue
                entries.append(Entry(item.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime))
        return entries

    def open(self, rel: str):
        path = self._path(rel)
        if not path.is_file():
            raise FileNotFoundError(rel)
        st = path.stat()
        return open(path, "rb"), st.st_size, st.st_mtime

    def mkdir(self, rel: str) -> None:
        self._path(rel).mkdir()

    def _move(self, rel: str, new_rel: str, entry: Entry) -> None:
        src = resolve_entry(self.base, rel)  # el último elemento puede ser un symlink: se mueve el enlace
        dst = resolve_inside(self.base, parent_rel(new_rel)) / name_of(new_rel)
        src.rename(dst)

    def delete(self, rel: str) -> None:
        entry = resolve_entry(self.base, clean_rel(rel))
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    def store(self, local: Path, rel: str) -> None:
        os.replace(local, self._path(rel))  # misma carpeta (ver staging_dir): renombrado atómico

    def staging_dir(self, dir_rel: str) -> Path:
        # Las partes se reciben junto al destino: al terminar, un renombrado atómico en el mismo disco
        return self._path(dir_rel)

    def free_space(self, dir_rel: str) -> int | None:
        try:
            return shutil.disk_usage(self._path(dir_rel)).free
        except OSError:
            return None

    def space(self, dir_rel: str = "") -> dict | None:
        try:
            usage = shutil.disk_usage(self._path(dir_rel))
        except OSError:
            return None
        return {"total": usage.total, "free": usage.free}

    def root_exists(self) -> bool:
        return self.base.exists()

    def ensure_root(self, home: bool = False) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.base, 0o750 if home else 0o770)
        except OSError:
            pass

    def __repr__(self) -> str:  # pragma: no cover - ayuda al depurar
        return f"LocalBackend({self.base})"
