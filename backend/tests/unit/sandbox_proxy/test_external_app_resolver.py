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

from onyx.external_apps.matching.engine import ActionMatch
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.resolvers import external_app as external_app_mod
from onyx.sandbox_proxy.resolvers.external_app import ExternalAppResolver
from tests.unit.sandbox_proxy.conftest import make_action_match
from tests.unit.sandbox_proxy.conftest import make_flow as _flow
from tests.unit.sandbox_proxy.conftest import make_resolved_sandbox as _sandbox


def _recorder_db_factory(ops: list[str]) -> Any:
    @contextmanager
    def factory(tenant_id: str) -> Iterator[Any]:
        ops.append(f"session:{tenant_id}")
        yield MagicMock()

    return factory


def _ctx(
    *,
    match: ActionMatch | None = None,
    db_factory: Any = None,
) -> InjectionContext:
    return InjectionContext(
        sandbox=_sandbox(tenant_id="tenant-7"),
        match=match,
        db_session_factory=db_factory
        if db_factory is not None
        else _recorder_db_factory([]),
    )


def test_claims_true_iff_match_present() -> None:
    """Host is irrelevant — the matcher has already attributed the request."""
    resolver = ExternalAppResolver()
    req = _flow(host="api.slack.com").request
    assert resolver.claims(req, _ctx(match=make_action_match())) is True
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

    match = make_action_match(external_app_id=99)
    ops: list[str] = []
    ctx = _ctx(match=match, db_factory=_recorder_db_factory(ops))

    headers = ExternalAppResolver().resolve(_flow().request, ctx)

    assert headers == {"Authorization": "Bearer real"}
    assert captured["external_app_id"] == 99
    assert captured["user_id"] == ctx.sandbox.user_id
    assert ops == ["session:tenant-7"]


def test_resolve_raises_when_match_is_none() -> None:
    """Contract violation safety net: `claims` guarantees `match` is set, but
    a Protocol bug must surface as a 403, not a NoneType crash inside SQL code."""
    resolver = ExternalAppResolver()
    with pytest.raises(CredentialUnavailableError):
        resolver.resolve(_flow().request, _ctx(match=None))
