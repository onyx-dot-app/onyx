"""Moving a live sandbox onto a new image without rebuilding it.

Cluster behaviour was verified separately on kind (k8s 1.35): the container
restarts even under ``restartPolicy: Never``, the emptyDir survives, and the
sidecar can be patched. These cover what that can't tell us — that we watch the
right signal for "the swap took", and that every refusal declines.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import (
    ImageMoveOutcome,
    SandboxImageTarget,
)

SANDBOX_ID = UUID("12345678-1234-1234-1234-1234567890ab")
OLD_DIGEST = "sha256:" + "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64
TARGET = SandboxImageTarget(
    ref=f"docker.io/onyxdotapp/sandbox@{NEW_DIGEST}", digest=NEW_DIGEST
)


@pytest.fixture(autouse=True)
def _fast_swap_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the give-up path from taking the production minute."""
    monkeypatch.setattr(ksm, "_IMAGE_SWAP_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(ksm, "_IMAGE_SWAP_POLL_SECONDS", 0.01)


def _pod(*, digest: str, ready: bool = True) -> client.V1Pod:
    pod = SimpleNamespace(
        status=SimpleNamespace(
            container_statuses=[
                SimpleNamespace(
                    name="sandbox",
                    image="docker.io/onyxdotapp/sandbox:latest",
                    image_id=f"docker.io/onyxdotapp/sandbox@{digest}",
                    ready=ready,
                    state=SimpleNamespace(running=object() if ready else None),
                )
            ],
            init_container_statuses=[],
        ),
    )
    return cast(client.V1Pod, pod)


def _manager(
    *, pods: list[client.V1Pod], sidecar_healthy: bool = True
) -> tuple[KubernetesSandboxManager, MagicMock]:
    """A manager whose pod reads walk ``pods``, holding the last one."""
    core_api = MagicMock()
    reads = list(pods)

    def next_pod(*_a: Any, **_kw: Any) -> client.V1Pod:
        return reads.pop(0) if len(reads) > 1 else reads[0]

    core_api.read_namespaced_pod.side_effect = next_pod
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    mgr._sidecar_client = MagicMock()  # type: ignore[attr-defined]
    mgr._sidecar_client.is_healthy.return_value = sidecar_healthy
    return mgr, core_api


def test_swap_patches_both_live_containers() -> None:
    """One patch, so a refusal can't leave a new agent on an old daemon."""
    mgr, core_api = _manager(pods=[_pod(digest=OLD_DIGEST), _pod(digest=NEW_DIGEST)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.MOVED

    body = core_api.patch_namespaced_pod.call_args.kwargs["body"]
    assert body["spec"]["containers"] == [{"name": "sandbox", "image": TARGET.ref}]
    assert body["spec"]["initContainers"] == [{"name": "sidecar", "image": TARGET.ref}]


def test_swap_waits_for_the_runtime_not_the_spec() -> None:
    """The spec updates at once; only the reported digest means the kubelet
    actually restarted the container."""
    mgr, _ = _manager(pods=[_pod(digest=OLD_DIGEST)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED


def test_swap_waits_for_readiness() -> None:
    """A restarted container that isn't ready cannot take a turn."""
    mgr, _ = _manager(pods=[_pod(digest=NEW_DIGEST, ready=False)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED


def test_swap_waits_for_the_sidecar() -> None:
    mgr, _ = _manager(pods=[_pod(digest=NEW_DIGEST)], sidecar_healthy=False)

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED


@pytest.mark.parametrize("status", [403, 422])
def test_swap_declines_when_the_cluster_refuses(status: int) -> None:
    """No `patch` permission, or a cluster rejecting the mutation. Both fall
    back to rebuilding rather than raising."""
    mgr, core_api = _manager(pods=[_pod(digest=OLD_DIGEST)])
    core_api.patch_namespaced_pod.side_effect = ApiException(status=status)

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED


def test_swap_declines_when_the_pod_is_gone() -> None:
    mgr, core_api = _manager(pods=[_pod(digest=OLD_DIGEST)])
    core_api.read_namespaced_pod.side_effect = ApiException(status=404)

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED
    core_api.patch_namespaced_pod.assert_not_called()


def test_swap_declines_when_the_pod_vanishes_mid_swap() -> None:
    """Evicted between the patch and the restart."""
    mgr, core_api = _manager(pods=[_pod(digest=OLD_DIGEST)])
    core_api.read_namespaced_pod.side_effect = [
        _pod(digest=OLD_DIGEST),
        ApiException(status=404),
    ]

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED


def test_kubernetes_never_asks_the_caller_to_provision() -> None:
    """Workspaces are emptyDirs that die with the pod, so they cannot outlive
    a discarded runtime."""
    mgr, _ = _manager(pods=[_pod(digest=OLD_DIGEST)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is not ImageMoveOutcome.NEEDS_PROVISION
