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
from onyx.server.features.build.sandbox.kubernetes import (
    kubernetes_sandbox_manager as k8s_mod,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
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
    ):
        self.base_url = base_url
        self.password = password
        self.closed = False
        _FakeProbeClient.created.append(self)

    def health_check_status(self) -> int:
        return 200 if self.password == _FRESH_PW else 401

    def close(self) -> None:
        self.closed = True


def _make_manager() -> KubernetesSandboxManager:
    # Bypass __init__ (which builds a real k8s client) — we only exercise the
    # in-process serve-transport plumbing.
    mgr = object.__new__(KubernetesSandboxManager)
    mgr._init_serve_state()
    mgr._namespace = "onyx-sandboxes"
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
    # Cache was reloaded from the backend exactly once after invalidation.
    assert load_mock.call_count == 2


def test_reuse_existing_pod_clears_stale_tombstone() -> None:
    mgr = _make_manager()
    sandbox_id = uuid4()

    # A prior terminate in this process tombstoned the sandbox; reusing a live
    # pod must clear it so event-bus creation can attach again.
    mgr._terminated_sandboxes.add(sandbox_id)

    with (
        mock.patch.object(k8s_mod, "SANDBOX_API_SERVER_URL", "http://api"),
        mock.patch.object(k8s_mod, "SANDBOX_PROXY_HOST", "proxy.local"),
        mock.patch.object(mgr, "_pod_exists_and_healthy", return_value=True),
        mock.patch.object(mgr, "_ensure_service_exists"),
        mock.patch.object(mgr, "_wait_for_pod_ready", return_value=True),
        mock.patch.object(mgr, "_wait_for_opencode_serve_ready", return_value=True),
    ):
        info = mgr.provision(
            sandbox_id=sandbox_id,
            user_id=uuid4(),
            tenant_id="public",
            llm_config=LLMProviderConfig(
                provider="openai",
                model_name="gpt-5-mini",
                api_key="sk-test",
                api_base=None,
            ),
            onyx_pat="pat-test",
        )

    assert info.sandbox_id == sandbox_id
    assert sandbox_id not in mgr._terminated_sandboxes
