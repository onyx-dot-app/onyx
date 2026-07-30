"""``_resolve_proxy_ip`` must resolve the egress-proxy hostAlias to the real
Service ClusterIP via the k8s API — not the api-server's OS resolver, which
under telepresence returns a synthetic, pod-unroutable IP. A numeric host (CI
passes the ClusterIP directly) is returned unchanged without an API call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kubernetes.client.rest import ApiException

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


def test_namespace_parsed_from_fqdn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ksm, "SANDBOX_PROXY_HOST", "onyx-sandbox-proxy.myrelease.svc.cluster.local"
    )
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_NAMESPACE", "onyx")
    mgr, core_api = _mgr()
    svc = MagicMock()
    svc.spec.cluster_ip = "10.0.0.5"
    core_api.read_namespaced_service.return_value = svc

    assert mgr._resolve_proxy_ip() == "10.0.0.5"
    core_api.read_namespaced_service.assert_called_once_with(
        name="onyx-sandbox-proxy", namespace="myrelease"
    )


def test_namespace_falls_back_to_config_for_bare_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "onyx-sandbox-proxy")
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_NAMESPACE", "proxy-ns")
    mgr, core_api = _mgr()
    svc = MagicMock()
    svc.spec.cluster_ip = "10.0.0.6"
    core_api.read_namespaced_service.return_value = svc

    assert mgr._resolve_proxy_ip() == "10.0.0.6"
    core_api.read_namespaced_service.assert_called_once_with(
        name="onyx-sandbox-proxy", namespace="proxy-ns"
    )


def test_missing_clusterip_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ksm, "SANDBOX_PROXY_HOST", "onyx-sandbox-proxy.onyx.svc.cluster.local"
    )
    monkeypatch.setattr(ksm, "_PROXY_RESOLVE_RETRY_ATTEMPTS", 1)
    mgr, core_api = _mgr()
    svc = MagicMock()
    svc.spec.cluster_ip = None
    core_api.read_namespaced_service.return_value = svc

    with pytest.raises(RuntimeError, match="ClusterIP"):
        mgr._resolve_proxy_ip()


def test_api_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ksm, "SANDBOX_PROXY_HOST", "onyx-sandbox-proxy.onyx.svc.cluster.local"
    )
    monkeypatch.setattr(ksm, "_PROXY_RESOLVE_RETRY_ATTEMPTS", 1)
    mgr, core_api = _mgr()
    core_api.read_namespaced_service.side_effect = ApiException(
        status=500, reason="boom"
    )

    with pytest.raises(RuntimeError, match="failed to resolve proxy ClusterIP"):
        mgr._resolve_proxy_ip()
