from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo


class _FakeOpencodeServeClient:
    event_bus: object | None = object()

    def __init__(
        self,
        base_url: str,
        password: str | None,
        *,
        event_bus: object | None = None,
        reload_password: Callable[[], str | None] | None = None,
        **_: Any,
    ) -> None:
        self.base_url = base_url
        self.password = password
        self.reload_password = reload_password
        _FakeOpencodeServeClient.event_bus = event_bus

    def __enter__(self) -> _FakeOpencodeServeClient:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def close(self) -> None:
        pass

    def ensure_session(
        self,
        opencode_session_id: str | None,
        *,
        directory: str,
        title: str | None = None,
    ) -> str:
        assert opencode_session_id is None
        assert directory.startswith("/workspace/sessions/")
        assert title is not None
        return "ses_fake"

    def delete_session(self, opencode_session_id: str, *, directory: str) -> bool:
        assert opencode_session_id == "ses_delete"
        assert directory.startswith("/workspace/sessions/")
        return True


def test_ensure_opencode_session_uses_unary_client_without_event_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_id = uuid4()
    build_session_id = uuid4()
    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    manager._init_serve_state()

    def load_connection_info(_: UUID) -> ServeConnectionInfo:
        return ServeConnectionInfo(
            base_url="http://sandbox.invalid:4096", password=None
        )

    def fail_if_bus_created(_: UUID, __: str) -> object:
        raise AssertionError("ensure_opencode_session should not create an event bus")

    manager._load_serve_connection_info = load_connection_info  # type: ignore[method-assign]
    manager._get_or_create_event_bus = fail_if_bus_created  # type: ignore[method-assign]
    monkeypatch.setattr(
        serve_transport,
        "OpencodeServeClient",
        _FakeOpencodeServeClient,
    )

    assert manager.ensure_opencode_session(sandbox_id, build_session_id) == "ses_fake"
    assert _FakeOpencodeServeClient.event_bus is None


def test_delete_opencode_session_uses_unary_client_without_event_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_id = uuid4()
    build_session_id = uuid4()
    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    manager._init_serve_state()

    def load_connection_info(_: UUID) -> ServeConnectionInfo:
        return ServeConnectionInfo(
            base_url="http://sandbox.invalid:4096", password=None
        )

    def fail_if_bus_created(_: UUID, __: str) -> object:
        raise AssertionError("delete_opencode_session should not create an event bus")

    manager._load_serve_connection_info = load_connection_info  # type: ignore[method-assign]
    manager._get_or_create_event_bus = fail_if_bus_created  # type: ignore[method-assign]
    monkeypatch.setattr(
        serve_transport,
        "OpencodeServeClient",
        _FakeOpencodeServeClient,
    )

    assert (
        manager.delete_opencode_session(sandbox_id, build_session_id, "ses_delete")
        is True
    )
    assert _FakeOpencodeServeClient.event_bus is None
