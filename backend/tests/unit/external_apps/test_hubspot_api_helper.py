"""The bundled ``hubspot_api.py`` sandbox helper: the friendly "paid write
seat" translation applied to denied HubSpot writes (ENG-4263). The helper is a
standalone script under the skills dir (not an importable package), so load it
by path. A denied write (missing scope) comes back as a raw 401/403 that reads
like a credential-injection failure and confuses the agent; these tests assert
we replace it with actionable text for writes while leaving reads / other
statuses untouched."""

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


def _http_error(status: int, message: str = "permission denied") -> urllib.error.HTTPError:
    body = json.dumps({"message": message}).encode("utf-8")
    return urllib.error.HTTPError(
        url="https://api.hubapi.com/crm/v3/objects/contacts",
        code=status,
        msg="error",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


def _run(monkeypatch: Any, capsys: Any, argv: list[str], error: Exception) -> tuple[int, dict[str, Any]]:
    """Invoke main with `_dispatch` raising `error`, returning (exit_code, parsed_json)."""

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
    assert "contacts" in msg


def test_write_denied_message_without_object_is_generic() -> None:
    msg = hubspot._write_denied_message(None)
    assert "paid HubSpot seat" in msg
    assert "this object" in msg


def test_is_write_scope_denial_matrix() -> None:
    assert hubspot._is_write_scope_denial("create", 401) is True
    assert hubspot._is_write_scope_denial("update", 403) is True
    # reads keep the raw error
    assert hubspot._is_write_scope_denial("list", 401) is False
    assert hubspot._is_write_scope_denial("get", 403) is False
    # non-auth statuses keep the raw error even on a write
    assert hubspot._is_write_scope_denial("create", 400) is False


# --- main() HTTPError translation ---


def test_create_401_returns_friendly_paid_seat_message(monkeypatch: Any, capsys: Any) -> None:
    code, out = _run(
        monkeypatch,
        capsys,
        ["create", "contacts", "--set", "email=a@b.co"],
        _http_error(401, "missing scopes"),
    )
    assert code == 1
    assert out["ok"] is False
    assert out["status"] == 401
    assert "paid HubSpot seat" in out["error"]
    assert "write access" in out["error"]
    assert "contacts" in out["error"]
    # original upstream message preserved for debugging
    assert out["detail"] == "missing scopes"


def test_update_403_returns_friendly_paid_seat_message(monkeypatch: Any, capsys: Any) -> None:
    code, out = _run(
        monkeypatch,
        capsys,
        ["update", "deals", "ID1", "--set", "amount=10"],
        _http_error(403, "forbidden"),
    )
    assert code == 1
    assert out["ok"] is False
    assert out["status"] == 403
    assert "paid HubSpot seat" in out["error"]
    assert "deals" in out["error"]
    assert out["detail"] == "forbidden"


def test_read_401_keeps_raw_error(monkeypatch: Any, capsys: Any) -> None:
    code, out = _run(
        monkeypatch,
        capsys,
        ["list", "contacts"],
        _http_error(401, "token expired"),
    )
    assert code == 1
    assert out["ok"] is False
    assert out["status"] == 401
    assert out["error"] == "token expired"
    assert "paid HubSpot seat" not in out["error"]
    assert "detail" not in out


def test_get_403_keeps_raw_error(monkeypatch: Any, capsys: Any) -> None:
    code, out = _run(
        monkeypatch,
        capsys,
        ["get", "companies", "ID1"],
        _http_error(403, "no access"),
    )
    assert code == 1
    assert out["error"] == "no access"
    assert "paid HubSpot seat" not in out["error"]


def test_write_400_keeps_raw_error(monkeypatch: Any, capsys: Any) -> None:
    # A non-auth failure on a write (e.g. validation) is a different problem and
    # must keep its original message.
    code, out = _run(
        monkeypatch,
        capsys,
        ["create", "contacts", "--set", "email=bad"],
        _http_error(400, "invalid email"),
    )
    assert code == 1
    assert out["status"] == 400
    assert out["error"] == "invalid email"
    assert "paid HubSpot seat" not in out["error"]
    assert "detail" not in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
