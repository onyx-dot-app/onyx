"""Unit tests for ``_ServeMixin._wait_for_opencode_serve_ready``.

Pins the multi-candidate probe contract: the readiness gate must succeed if
EITHER the Service ``base_url`` (FQDN) OR the pod-IP health-check URL answers
``GET /doc`` with 200. The FQDN is probed first (it routes in prod and under
telepresence, which proxies cluster DNS but not raw pod IPs); the pod IP is the
fallback for out-of-cluster CI (routes pod IPs, no cluster DNS).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from onyx.server.features.build.sandbox.opencode.serve_client import OpencodeServeClient
from onyx.server.features.build.sandbox.serve_transport import _ServeMixin
from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo

_SBX = UUID("12345678-1234-1234-1234-1234567890ab")
_POD_IP_URL = "http://10.244.0.97:4096"
_SERVICE_URL = "http://sandbox-x.onyx-sandboxes.svc.cluster.local:4096"
_PASSWORD = "hunter2"


class _FakeManager(_ServeMixin):
    """Minimal mixin host with a Service-FQDN base_url + a pod-IP health-check
    URL, mirroring the K8s manager's split addressing."""

    def __init__(self, health_check_url: str | None) -> None:
        self._health_check_url = health_check_url
        self._init_serve_state()

    def _load_serve_connection_info(
        self,
        sandbox_id: UUID,  # noqa: ARG002
    ) -> ServeConnectionInfo | None:
        return ServeConnectionInfo(base_url=_SERVICE_URL, password=_PASSWORD)

    def _serve_health_check_base_url(self, sandbox_id: UUID) -> str | None:  # noqa: ARG002
        return self._health_check_url


def test_ready_via_service_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """FQDN answers, pod IP would refuse → ready via the preferred candidate."""
    probed: list[str] = []

    def fake_status(self: OpencodeServeClient) -> int | None:
        probed.append(self._base_url)
        return None if self._base_url == _POD_IP_URL else 200

    monkeypatch.setattr(OpencodeServeClient, "health_check_status", fake_status)

    mgr = _FakeManager(health_check_url=_POD_IP_URL)
    assert mgr._wait_for_opencode_serve_ready(_SBX, timeout=5.0) is True
    assert probed[0] == _SERVICE_URL


def test_ready_via_pod_ip_when_dns_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FQDN unresolvable, pod IP answers → ready via the fallback candidate."""
    probed: list[str] = []

    def fake_status(self: OpencodeServeClient) -> int | None:
        probed.append(self._base_url)
        return None if self._base_url == _SERVICE_URL else 200

    monkeypatch.setattr(OpencodeServeClient, "health_check_status", fake_status)

    mgr = _FakeManager(health_check_url=_POD_IP_URL)
    assert mgr._wait_for_opencode_serve_ready(_SBX, timeout=5.0) is True
    assert probed[0] == _SERVICE_URL
    assert _POD_IP_URL in probed


def test_not_ready_when_no_candidate_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both candidates refuse for the whole window → not ready."""

    def fake_status(self: OpencodeServeClient) -> int | None:  # noqa: ARG001
        return None

    monkeypatch.setattr(OpencodeServeClient, "health_check_status", fake_status)

    mgr = _FakeManager(health_check_url=_POD_IP_URL)
    assert mgr._wait_for_opencode_serve_ready(_SBX, timeout=0.4) is False
