"""Collision-free resource names for the Firecracker sandbox runtime."""

from __future__ import annotations

from uuid import UUID

from onyx.server.features.build.sandbox.kubernetes_runtime import (
    KubernetesRuntime,
)

_DNS_LABEL_MAX = 63
_LONGEST_SUFFIX = "-opencode-auth"


def test_pod_name_stays_within_dns_label_limit() -> None:
    manager = object.__new__(KubernetesRuntime)

    pod_name = manager.pod_name(UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"))

    assert len(pod_name) + len(_LONGEST_SUFFIX) <= _DNS_LABEL_MAX
    assert pod_name == pod_name.lower()
    assert all(c.isalnum() or c == "-" for c in pod_name)


def test_shared_uuid_prefixes_do_not_share_pod_service_or_secret_names() -> None:
    runtime = object.__new__(KubernetesRuntime)
    first = UUID("12345678-0000-0000-0000-000000000001")
    second = UUID("12345678-0000-0000-0000-000000000002")
    first_name = runtime.pod_name(first)
    second_name = runtime.pod_name(second)
    assert first_name == f"sandbox-{first.hex}"
    assert second_name == f"sandbox-{second.hex}"
    assert first_name != second_name
    assert first_name + _LONGEST_SUFFIX != second_name + _LONGEST_SUFFIX
