"""Unit tests for `ExternalAppResolver`.

The resolver is a thin wrapper around `resolve_injection_headers`; coverage
focuses on the dispatcher seam — the claim rule and the exception
translation. The renderer's per-header fail-open behaviour lives in
`tests/external_dependency_unit/craft/test_credential_injection.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

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
    match=make_action_match(),
    db_factory: Any = None,  # type: ignore[no-untyped-def]
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
    assert resolver.claims("api.slack.com", _ctx()) is True
    assert resolver.claims("anything.example", _ctx()) is True
    assert resolver.claims("api.slack.com", _ctx(match=None)) is False


def test_resolve_delegates_to_resolve_injection_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opens a tenant-scoped session and forwards `(external_app_id, user_id)`
    to the renderer; returns whatever the renderer returned."""
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
    flow = _flow()

    headers = ExternalAppResolver().resolve(flow.request, ctx)

    assert headers == {"Authorization": "Bearer real"}
    assert captured["external_app_id"] == 99
    assert captured["user_id"] == ctx.sandbox.user_id
    assert ops == ["session:tenant-7"]


def test_resolve_translates_db_error_to_credential_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DB blip becomes the explicit fail-closed signal so the dispatcher
    renders a 403, not a silent forward."""

    def _boom(_db: Any, _aid: int, _uid: Any) -> dict[str, str]:
        raise RuntimeError("db down")

    monkeypatch.setattr(external_app_mod, "resolve_injection_headers", _boom)

    with pytest.raises(CredentialUnavailableError):
        ExternalAppResolver().resolve(_flow().request, _ctx())
