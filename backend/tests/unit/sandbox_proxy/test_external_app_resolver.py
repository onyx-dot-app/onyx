"""Unit tests for `ExternalAppResolver`.

The resolver is a thin wrapper around `resolve_injection_headers`; coverage
focuses on the claim rule and the contract violations the dispatcher relies
on. The renderer's per-header fail-open behaviour is pinned against a real
DB in `tests/external_dependency_unit/craft/test_credential_injection.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.external_apps.matching.engine import RequestMatch
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.resolvers import external_app as external_app_mod
from onyx.sandbox_proxy.resolvers.external_app import ExternalAppResolver
from tests.unit.sandbox_proxy.conftest import make_flow as _flow
from tests.unit.sandbox_proxy.conftest import make_request_match
from tests.unit.sandbox_proxy.conftest import make_resolved_sandbox as _sandbox


@pytest.fixture(autouse=True)
def _noop_token_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default `ensure_fresh_credentials` to a no-op so these tests pin the
    claim rule and rendering contract; the refresh-seam test re-patches it.
    The refresh mechanics live in `tests/unit/external_apps/test_token_refresh.py`."""
    monkeypatch.setattr(
        external_app_mod, "ensure_fresh_credentials", lambda *_a, **_k: None
    )


def _recorder_db_factory(ops: list[str]) -> Any:
    @contextmanager
    def factory(tenant_id: str) -> Iterator[Any]:
        ops.append(f"session:{tenant_id}")
        yield MagicMock()

    return factory


def _ctx(*, match: RequestMatch | None = None) -> InjectionContext:
    return InjectionContext(sandbox=_sandbox(tenant_id="tenant-7"), match=match)


def test_claims_true_iff_match_present() -> None:
    """Host is irrelevant — the matcher has already attributed the request."""
    resolver = ExternalAppResolver()
    req = _flow(host="api.slack.com").request
    assert resolver.claims(req, _ctx(match=make_request_match())) is True
    assert resolver.claims(req, _ctx(match=None)) is False


def test_resolve_forwards_external_app_id_user_id_and_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolver opens a tenant-scoped session and forwards
    `(external_app_id, user_id)` to the renderer."""
    captured: dict[str, Any] = {}

    def _fake(db: Any, external_app_id: int, user_id: Any) -> dict[str, str]:
        captured["db"] = db
        captured["external_app_id"] = external_app_id
        captured["user_id"] = user_id
        return {"Authorization": "Bearer real"}

    monkeypatch.setattr(external_app_mod, "resolve_injection_headers", _fake)
    ops: list[str] = []
    monkeypatch.setattr(
        external_app_mod, "get_session_with_tenant", _recorder_db_factory(ops)
    )

    match = make_request_match(external_app_id=99)
    ctx = _ctx(match=match)

    headers = ExternalAppResolver().resolve(_flow().request, ctx)

    assert headers == {"Authorization": "Bearer real"}
    assert captured["external_app_id"] == 99
    assert captured["user_id"] == ctx.sandbox.user_id
    assert ops == ["session:tenant-7"]


def test_resolve_refreshes_token_before_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolver refreshes an expiring OAuth token (via `ensure_fresh_credentials`,
    handed the tenant + ids) before rendering headers, so the injected `Bearer` is
    live. The refresh mechanics themselves are pinned in
    `tests/unit/external_apps/test_token_refresh.py`."""
    calls: list[tuple[str, int, Any]] = []

    def _ensure(tenant_id: str, app_id: int, user_id: Any) -> None:
        calls.append((tenant_id, app_id, user_id))

    monkeypatch.setattr(external_app_mod, "ensure_fresh_credentials", _ensure)
    monkeypatch.setattr(
        external_app_mod,
        "resolve_injection_headers",
        lambda *_a, **_k: {"Authorization": "Bearer real"},
    )
    monkeypatch.setattr(
        external_app_mod, "get_session_with_tenant", _recorder_db_factory([])
    )

    match = make_request_match(external_app_id=99)
    ctx = _ctx(match=match)

    headers = ExternalAppResolver().resolve(_flow().request, ctx)

    assert headers == {"Authorization": "Bearer real"}
    assert calls == [("tenant-7", 99, ctx.sandbox.user_id)]


def test_resolve_raises_when_match_is_none() -> None:
    """Contract violation safety net: `claims` guarantees `match` is set, but
    a Protocol bug must surface as a 403, not a NoneType crash inside SQL code."""
    resolver = ExternalAppResolver()
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(_flow().request, _ctx(match=None))
