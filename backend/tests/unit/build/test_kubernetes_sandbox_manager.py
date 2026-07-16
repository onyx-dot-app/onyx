"""Unit coverage for Kubernetes sandbox manager helpers."""

from __future__ import annotations

from uuid import UUID

from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.kubernetes import kubernetes_sandbox_manager
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)

# K8s object names must be a DNS label: <=63 chars, lowercase alphanumerics
# and hyphens. ``_get_pod_name`` is the prefix for the pod, service, and the
# ``-opencode-auth`` secret, so the longest derived name must still fit.
_DNS_LABEL_MAX = 63
_LONGEST_SUFFIX = "-opencode-auth"


def test_provisioning_lock_covers_all_startup_timeouts() -> None:
    expected_timeout = (
        kubernetes_sandbox_manager.OPENCODE_HISTORY_RESTORE_TIMEOUT_SECONDS
        + kubernetes_sandbox_manager.POD_READY_TIMEOUT_SECONDS
        + serve_transport.OPENCODE_SERVE_READY_TIMEOUT_SECONDS
        + kubernetes_sandbox_manager.RESOURCE_DELETION_TIMEOUT_SECONDS
    )

    assert kubernetes_sandbox_manager.OPENCODE_HISTORY_RESTORE_TIMEOUT_SECONDS == 90.0
    assert kubernetes_sandbox_manager.PROVISION_LOCK_TIMEOUT_SECONDS == 180.0
    assert kubernetes_sandbox_manager.PROVISION_LOCK_TIMEOUT_SECONDS == expected_timeout


def test_pod_name_stays_within_dns_label_limit() -> None:
    manager = KubernetesSandboxManager.__new__(KubernetesSandboxManager)

    # The name length is constant (``_get_pod_name`` truncates to the first 8
    # hex chars); this all-f UUID just exercises the full alphanumeric range so
    # the lowercase / DNS-label character-set assertions below are meaningful.
    pod_name = manager._get_pod_name(UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"))

    assert len(pod_name) + len(_LONGEST_SUFFIX) <= _DNS_LABEL_MAX
    assert pod_name == pod_name.lower()
    assert all(c.isalnum() or c == "-" for c in pod_name)
