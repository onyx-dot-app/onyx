"""``_resolve_proxy_ip`` must resolve the egress-proxy hostAlias to the real
Service ClusterIP via the k8s API — not the api-server's OS resolver, which
under telepresence returns a synthetic, pod-unroutable IP. A numeric host (CI
passes the ClusterIP directly) is returned unchanged without an API call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


def _mgr() -> tuple[KubernetesSandboxManager, MagicMock]:
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._namespace = "onyx-sandboxes"  # type: ignore[attr-defined]
    core_api = MagicMock()
    mgr._core_api = core_api  # type: ignore[attr-defined]
    return mgr, core_api


def test_numeric_host_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "10.96.188.108")
    mgr, core_api = _mgr()
    assert mgr._resolve_proxy_ip() == "10.96.188.108"
    core_api.read_namespaced_service.assert_not_called()


def test_fqdn_resolved_to_clusterip_via_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ksm, "SANDBOX_PROXY_HOST", "onyx-sandbox-proxy.onyx.svc.cluster.local"
    )
    mgr, core_api = _mgr()
    svc = MagicMock()
    svc.spec.cluster_ip = "10.96.188.108"
    core_api.read_namespaced_service.return_value = svc

    assert mgr._resolve_proxy_ip() == "10.96.188.108"
    core_api.read_namespaced_service.assert_called_once_with(
        name="onyx-sandbox-proxy", namespace="onyx"
    )
