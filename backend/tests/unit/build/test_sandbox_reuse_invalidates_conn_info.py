"""Regression test for the "sandbox stuck initializing" bug.

When ``KubernetesSandboxManager.provision`` reuses an already-healthy pod, it
must drop its cached :class:`ServeConnectionInfo`. The pod may have been
re-provisioned with a fresh opencode Secret (new HTTP-Basic password) since this
api_server process last cached the connection info, and K8s does not propagate
Secret updates into a running container's env. A stale cached password would
401 against the pod forever, so the readiness probe never sees 200 and the
sandbox is stuck "initializing".
"""

from unittest import mock
from uuid import uuid4

from onyx.server.features.build.sandbox.kubernetes import (
    kubernetes_sandbox_manager as k8s_mod,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo


def _make_manager() -> KubernetesSandboxManager:
    # Bypass __init__ (which builds a real k8s client) — we only exercise the
    # in-process cache plumbing from the serve-transport mixin.
    mgr = object.__new__(KubernetesSandboxManager)
    mgr._init_serve_state()
    mgr._namespace = "onyx-sandboxes"
    return mgr


def test_reuse_existing_pod_invalidates_stale_connection_info() -> None:
    mgr = _make_manager()
    sandbox_id = uuid4()

    # Seed stale state from a prior pod incarnation: a cached password and a
    # leftover tombstone. Both would make the reused pod unreachable.
    mgr._serve_conn_info[sandbox_id] = ServeConnectionInfo(
        base_url="http://stale-pod:4096", password="stale-password"
    )
    mgr._terminated_sandboxes.add(sandbox_id)

    with (
        mock.patch.object(k8s_mod, "SANDBOX_API_SERVER_URL", "http://api"),
        mock.patch.object(k8s_mod, "SANDBOX_PROXY_HOST", "proxy.local"),
        mock.patch.object(mgr, "_pod_exists_and_healthy", return_value=True),
        mock.patch.object(mgr, "_ensure_service_exists"),
        mock.patch.object(mgr, "_wait_for_pod_ready", return_value=True),
        mock.patch.object(
            mgr, "_wait_for_opencode_serve_ready", return_value=True
        ) as ready,
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

    # Reuse branch returned a RUNNING sandbox...
    assert info.sandbox_id == sandbox_id
    # ...and the readiness probe ran *after* the cache was cleared, so it would
    # re-read the current Secret password instead of the stale one.
    ready.assert_called_once_with(sandbox_id)
    assert sandbox_id not in mgr._serve_conn_info
    assert sandbox_id not in mgr._terminated_sandboxes
