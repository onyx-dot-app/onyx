"""Regression tests for the "sandbox stuck initializing" bug.

opencode-serve sits behind HTTP Basic auth whose password lives in a per-pod
k8s Secret, read into the container's env at start. The api_server caches that
password in memory. When a pod is re-provisioned with a fresh Secret, the cached
password goes stale — and K8s never pushes Secret updates into a running
container's env. Previously the readiness probe just saw a non-200 and polled
the same stale password until timeout ("opencode-serve never became ready"),
leaving the sandbox stuck "initializing".

``_wait_for_opencode_serve_ready`` now probes with the cached password first and,
on a 401, re-reads the current password from the backend and retries once.
"""

from unittest import mock
from uuid import uuid4

from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.manager import (
    SandboxManager,
)
from onyx.server.features.build.sandbox.opencode.serve_client import ClientTimeouts
from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo

_STALE_PW = "stale-password"
_FRESH_PW = "fresh-password"


class _FakeProbeClient:
    """Stand-in for OpencodeServeClient: 200 only for the fresh password."""

    created: list["_FakeProbeClient"] = []

    def __init__(
        self,
        base_url: str,
        password: str | None,
        *,
        event_bus: object = None,  # noqa: ARG002
        timeouts: ClientTimeouts,
    ) -> None:
        self.base_url = base_url
        self.password = password
        self.timeouts = timeouts
        self.closed = False
        self.probe_timeouts: list[float] = []
        _FakeProbeClient.created.append(self)

    def health_check_status(self, *, timeout: float) -> int:
        self.probe_timeouts.append(timeout)
        return 200 if self.password == _FRESH_PW else 401

    def close(self) -> None:
        self.closed = True


def _make_manager() -> SandboxManager:
    # Bypass __init__ (which builds a real k8s client) — we only exercise the
    # in-process serve-transport plumbing.
    mgr = object.__new__(SandboxManager)
    mgr._init_serve_state()
    return mgr


def test_wait_for_opencode_serve_ready_resets_password_on_401() -> None:
    mgr = _make_manager()
    sandbox_id = uuid4()

    _FakeProbeClient.created.clear()
    with (
        mock.patch.object(mgr, "_serve_health_check_base_url", return_value=None),
        # First load returns the stale cached password; after the 401-triggered
        # invalidation, the reload returns the current one.
        mock.patch.object(
            mgr,
            "_load_serve_connection_info",
            side_effect=[
                ServeConnectionInfo(base_url="http://pod:4096", password=_STALE_PW),
                ServeConnectionInfo(base_url="http://pod:4096", password=_FRESH_PW),
            ],
        ) as load_mock,
        mock.patch.object(serve_transport, "OpencodeServeClient", _FakeProbeClient),
    ):
        ready = mgr._wait_for_opencode_serve_ready(sandbox_id, timeout=5.0)

    assert ready is True
    # Probed with the stale password, got 401, rebuilt with the fresh one.
    assert [c.password for c in _FakeProbeClient.created] == [_STALE_PW, _FRESH_PW]
    assert _FakeProbeClient.created[0].closed is True
    assert _FakeProbeClient.created[1].closed is True
    assert all(c.timeouts.connect_timeout == 5.0 for c in _FakeProbeClient.created)
    stale_timeout = _FakeProbeClient.created[0].probe_timeouts[0]
    fresh_timeout = _FakeProbeClient.created[1].probe_timeouts[0]
    assert 0 < fresh_timeout <= stale_timeout <= 5.0
    # Cache was reloaded from the backend exactly once after invalidation.
    assert load_mock.call_count == 2
