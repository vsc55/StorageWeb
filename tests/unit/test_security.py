import os

import pytest

from storageweb.core import security
from storageweb.core.security import (LoginThrottle, PathError, resolve_entry, resolve_inside, safe_filename,
                               safe_username_for_path)
from storageweb.web.guards import safe_next


@pytest.mark.parametrize("raw, expected", [
    ("informe año.pdf", "informe año.pdf"),
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\x\\doc.txt", "doc.txt"),
    ("a<b>c:d|e?.txt", "a_b_c_d_e_.txt"),
    ("tab\there.txt", "tab_here.txt"),
    ("final. ", "final"),
    (".bashrc", ".bashrc"),
    ("e\u0301.txt", "\u00e9.txt"),  # normaliza a NFC
])
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


@pytest.mark.parametrize("raw", ["", ".", "..", "   ", "/", security.UPLOAD_TMP_PREFIX + "x.part"])
def test_safe_filename_rejects(raw):
    with pytest.raises(ValueError):
        safe_filename(raw)


def test_safe_filename_truncates_to_255_bytes_keeping_extension():
    name = safe_filename("ñ" * 300 + ".pdf")
    assert len(name.encode("utf-8")) <= 255
    assert name.endswith(".pdf")


def test_safe_filename_windows_reserved(monkeypatch):
    monkeypatch.setattr(security, "IS_WINDOWS", True)
    with pytest.raises(ValueError):
        safe_filename("CON.txt")
    assert safe_filename("CONSOLA.txt") == "CONSOLA.txt"


def test_safe_username_for_path():
    assert safe_username_for_path("Juan@Contoso.com") == "juan@contoso.com"
    assert safe_username_for_path("a/b\\c") == "a_b_c"
    with pytest.raises(ValueError):
        safe_username_for_path("..")


def test_resolve_inside_ok(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    assert resolve_inside(tmp_path, "a/b") == (tmp_path / "a" / "b").resolve()
    assert resolve_inside(tmp_path, "") == tmp_path.resolve()
    assert resolve_inside(tmp_path, "./a//b/") == (tmp_path / "a" / "b").resolve()


@pytest.mark.parametrize("sub", ["..", "a/../..", "../x", "a/../../x"])
def test_resolve_inside_rejects_dotdot(tmp_path, sub):
    (tmp_path / "a").mkdir()
    with pytest.raises(PathError):
        resolve_inside(tmp_path / "a", sub)


def test_resolve_inside_absolute_never_escapes(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    # Una ruta absoluta se rechaza (Windows, por la unidad) o se trata como relativa a base (POSIX)
    try:
        result = resolve_inside(base, str(tmp_path / "otro"))
    except PathError:
        return
    assert base.resolve() in result.parents


def _symlink(link, target, is_dir=False):
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("El sistema no permite crear symlinks")


def test_resolve_inside_rejects_symlink_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (tmp_path / "secreto").mkdir()
    _symlink(base / "fuga", tmp_path / "secreto", is_dir=True)
    with pytest.raises(PathError):
        resolve_inside(base, "fuga")


def test_safe_next(app):
    with app.test_request_context():
        assert safe_next("/f/home/x") == "/f/home/x"
        for bad in ["//evil.com", "https://evil.com", "/\\evil.com", "", None, "javascript:alert(1)"]:
            assert safe_next(bad) == "/"


def test_login_throttle(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: now[0])
    t = LoginThrottle(max_failures=3, lockout_seconds=60)
    for _ in range(3):
        assert not t.is_blocked("1.1.1.1", "ana")
        t.failure("1.1.1.1", "ana")
    assert t.is_blocked("1.1.1.1", "ana")
    assert t.is_blocked("2.2.2.2", "ANA")       # mismo usuario desde otra IP
    assert t.is_blocked("1.1.1.1", "otro")      # misma IP con otro usuario
    assert not t.is_blocked("2.2.2.2", "otro")
    now[0] += 61
    assert not t.is_blocked("1.1.1.1", "ana")


def test_login_throttle_success_resets_user():
    t = LoginThrottle(max_failures=2, lockout_seconds=60)
    t.failure("1.1.1.1", "ana")
    t.success("1.1.1.1", "ana")
    t.failure("9.9.9.9", "ana")
    assert not t.is_blocked("9.9.9.9", "ana")


def test_resolve_entry(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.txt").write_text("x")
    assert resolve_entry(tmp_path, "a/f.txt") == tmp_path.resolve() / "a" / "f.txt"
    for bad in ["", "a/no-existe", "a/..", "../x"]:
        with pytest.raises(PathError):
            resolve_entry(tmp_path, bad)
