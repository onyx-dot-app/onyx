"""The bundled ``hubspot_api.py`` sandbox helper: the friendly "paid write
seat" translation applied to denied HubSpot writes (ENG-4263). The helper is a
standalone script under the skills dir (not an importable package), so load it
by path. The CRM write scopes are optional OAuth scopes, so an account without
a paid write seat gets a raw 401/403 on writes that reads like a
credential-injection failure; these tests assert we replace it with actionable
text for writes while leaving reads / other statuses untouched. No network and
no onyx imports."""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_HELPER = (
    Path(__file__).resolve().parents[3]
    / "onyx/skills/builtin"
    / "hubspot/hubspot_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hubspot_api", _HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hubspot = _load()


def _http_error(status: int, message: str) -> urllib.error.HTTPError:
    body = json.dumps({"message": message}).encode("utf-8")
    return urllib.error.HTTPError(
        url="https://api.hubapi.com/crm/v3/objects/contacts",
        code=status,
        msg="error",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    error: Exception,
) -> tuple[int, dict[str, Any]]:
    """Invoke main() with `_dispatch` raising `error`; return (exit_code, json)."""

    def _boom(_a: Any) -> Any:
        raise error

    monkeypatch.setattr(hubspot, "_dispatch", _boom)
    code = hubspot.main(["hubspot_api.py", *argv])
    out = capsys.readouterr().out.strip()
    return code, json.loads(out)


# --- pure helpers ---


def test_write_denied_message_includes_object() -> None:
    msg = hubspot._write_denied_message("contacts")
    assert "paid HubSpot seat" in msg
    assert "write access" in msg
    assert "to contacts" in msg
    assert "reconnect HubSpot in Onyx" in msg


def test_write_denied_message_without_object_is_generic() -> None:
    msg = hubspot._write_denied_message(None)
    assert "paid HubSpot seat" in msg
    assert "to this object" in msg


@pytest.mark.parametrize(
    "cmd,status,expected",
    [
        ("create", 401, True),
        ("create", 403, True),
        ("update", 401, True),
        ("update", 403, True),
        # reads keep the raw error
        ("list", 401, False),
        ("get", 403, False),
        ("search", 401, False),
        ("owners", 401, False),
        ("call", 401, False),
        (None, 401, False),
        # non-auth statuses keep the raw error even on a write
        ("create", 400, False),
        ("update", 404, False),
        ("create", 429, False),
    ],
)
def test_is_write_scope_denial_matrix(
    cmd: str | None, status: int, expected: bool
) -> None:
    assert hubspot._is_write_scope_denial(cmd, status) is expected


# --- main() HTTPError translation ---


@pytest.mark.parametrize("status", [401, 403])
def test_create_denied_returns_friendly_paid_seat_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    code, out = _run(
        monkeypatch,
        capsys,
        ["create", "contacts", "--set", "email=a@b.co"],
        _http_error(status, "missing scopes"),
    )
    assert code == 1
    assert out["ok"] is False
    assert out["status"] == status
    assert "paid HubSpot seat" in out["error"]
    assert "write access" in out["error"]
    assert "contacts" in out["error"]
    # original upstream message preserved for debugging
    assert out["detail"] == "missing scopes"


@pytest.mark.parametrize("status", [401, 403])
def test_update_denied_returns_friendly_paid_seat_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    code, out = _run(
        monkeypatch,
        capsys,
        ["update", "deals", "ID1", "--set", "amount=10"],
        _http_error(status, "forbidden"),
    )
    assert code == 1
    assert out["ok"] is False
    assert out["status"] == status
    assert "paid HubSpot seat" in out["error"]
    assert "deals" in out["error"]
    assert out["detail"] == "forbidden"


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "contacts"],
        ["get", "companies", "ID1"],
        ["search", "deals", "acme"],
        ["owners"],
    ],
)
def test_read_401_keeps_raw_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    code, out = _run(monkeypatch, capsys, argv, _http_error(401, "token expired"))
    assert code == 1
    assert out == {"ok": False, "status": 401, "error": "token expired"}


def test_read_403_keeps_raw_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(
        monkeypatch,
        capsys,
        ["get", "companies", "ID1"],
        _http_error(403, "no access"),
    )
    assert code == 1
    assert out == {"ok": False, "status": 403, "error": "no access"}


def test_write_400_keeps_raw_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A non-auth failure on a write (e.g. validation) is a different problem and
    # must keep its original message.
    code, out = _run(
        monkeypatch,
        capsys,
        ["create", "contacts", "--set", "email=bad"],
        _http_error(400, "invalid email"),
    )
    assert code == 1
    assert out == {"ok": False, "status": 400, "error": "invalid email"}


def test_write_denied_with_non_json_body_preserves_raw_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    err = urllib.error.HTTPError(
        url="https://api.hubapi.com/crm/v3/objects/deals",
        code=401,
        msg="error",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b"Unauthorized"),
    )
    code, out = _run(
        monkeypatch, capsys, ["create", "deals", "--set", "dealname=x"], err
    )
    assert code == 1
    assert "paid HubSpot seat" in out["error"]
    assert out["detail"] == "Unauthorized"
