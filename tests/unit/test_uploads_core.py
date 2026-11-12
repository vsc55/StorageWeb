"""Lógica de subidas por partes sin HTTP."""
import io

import pytest

from storageweb.core import uploads as core


def test_chunk_size():
    assert core.chunk_size(2048) == 32 * core.MB
    assert core.chunk_size(5) == 4 * core.MB
    assert core.chunk_size(1) == core.MB


def test_validate_size():
    assert core.validate_size("10", 0) == 10
    assert core.validate_size(core.MB, 1) == core.MB
    with pytest.raises(core.UploadError) as exc:
        core.validate_size(core.MB + 1, 1)
    assert exc.value.status == 413
    for bad in (-1, "x", None):
        with pytest.raises(core.UploadError):
            core.validate_size(bad, 0)


def test_append_and_finalize(tmp_path):
    part = core.part_path(tmp_path, "abc")
    part.touch()
    assert core.append(part, io.BytesIO(b"hola "), 0, 10) == 5
    with pytest.raises(core.UploadError) as exc:
        core.append(part, io.BytesIO(b"x"), 0, 10)
    assert exc.value.status == 409 and exc.value.extra["received"] == 5
    assert core.append(part, io.BytesIO(b"mundo"), 5, 10) == 10
    final = core.finalize(part, tmp_path, "saludo.txt", 10)
    assert final.read_bytes() == b"hola mundo" and not part.exists()


def test_append_overflow_truncates(tmp_path):
    part = core.part_path(tmp_path, "abc")
    part.write_bytes(b"12")
    with pytest.raises(core.UploadError):
        core.append(part, io.BytesIO(b"3456"), 2, 4)
    assert part.read_bytes() == b"12"


def test_finalize_incomplete_and_missing(tmp_path):
    part = core.part_path(tmp_path, "abc")
    part.write_bytes(b"12")
    with pytest.raises(core.UploadError) as exc:
        core.finalize(part, tmp_path, "x", 5)
    assert exc.value.status == 409
    core.discard(part)
    core.discard(part)  # idempotente
    with pytest.raises(core.UploadError) as exc:
        core.received(part)
    assert exc.value.status == 404


def test_finalize_never_overwrites(tmp_path):
    (tmp_path / "a.txt").write_text("viejo")
    part = core.part_path(tmp_path, "abc")
    part.write_bytes(b"nuevo")
    final = core.finalize(part, tmp_path, "a.txt", 5)
    assert final.name == "a (1).txt" and (tmp_path / "a.txt").read_text() == "viejo"
