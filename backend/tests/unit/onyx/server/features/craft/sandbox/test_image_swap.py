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


def _pod(*, digest: str | None, ready: bool = True) -> client.V1Pod:
    """Enough of a pod for both the digest check and the real readiness waiter."""
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="sandbox-abc", resource_version="1"),
        spec=SimpleNamespace(init_containers=[]),
        status=SimpleNamespace(
            phase="Running",
            conditions=[
                SimpleNamespace(type="Ready", status="True" if ready else "False")
            ],
            container_statuses=[
                SimpleNamespace(
                    name="sandbox",
                    image="docker.io/onyxdotapp/sandbox:latest",
                    image_id=(
                        f"docker.io/onyxdotapp/sandbox@{digest}" if digest else None
                    ),
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
) -> tuple[KubernetesSandboxManager, MagicMock, MagicMock]:
    """A manager whose pod reads walk ``pods``, holding the last one."""
    core_api = MagicMock()
    reads = list(pods)

    def next_pod(*_a: Any, **_kw: Any) -> client.V1Pod:
        return reads.pop(0) if len(reads) > 1 else reads[0]

    core_api.read_namespaced_pod.side_effect = next_pod
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    sidecar = MagicMock()
    sidecar.is_healthy.return_value = sidecar_healthy
    mgr._sidecar_client = sidecar  # type: ignore[attr-defined]
    return mgr, core_api, sidecar


def test_swap_patches_both_live_containers() -> None:
    """One patch, so a refusal can't leave a new agent on an old daemon."""
    mgr, core_api, _sidecar = _manager(
        pods=[_pod(digest=OLD_DIGEST), _pod(digest=NEW_DIGEST)]
    )

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.MOVED

    body = core_api.patch_namespaced_pod.call_args.kwargs["body"]
    assert body["spec"]["containers"] == [{"name": "sandbox", "image": TARGET.ref}]
    assert body["spec"]["initContainers"] == [{"name": "sidecar", "image": TARGET.ref}]


def test_swap_waits_for_the_runtime_not_the_spec() -> None:
    """The spec updates at once; only the reported digest means the kubelet
    actually restarted the container."""
    mgr, _, sidecar = _manager(pods=[_pod(digest=OLD_DIGEST)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.DISRUPTED


def test_swap_waits_for_readiness() -> None:
    """A restarted container that isn't ready cannot take a turn."""
    mgr, _, sidecar = _manager(pods=[_pod(digest=NEW_DIGEST, ready=False)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.DISRUPTED


def test_swap_waits_for_the_sidecar() -> None:
    mgr, _, sidecar = _manager(pods=[_pod(digest=NEW_DIGEST)], sidecar_healthy=False)

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.DISRUPTED


@pytest.mark.parametrize("status", [403, 422])
def test_swap_declines_when_the_cluster_refuses(status: int) -> None:
    """No `patch` permission, or a cluster rejecting the mutation. Nothing was
    touched, so both fall back to rebuilding rather than raising."""
    mgr, core_api, _sidecar = _manager(pods=[_pod(digest=OLD_DIGEST)])
    core_api.patch_namespaced_pod.side_effect = ApiException(status=status)

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED


def test_swap_declines_when_the_pod_is_gone() -> None:
    mgr, core_api, _sidecar = _manager(pods=[_pod(digest=OLD_DIGEST)])
    core_api.patch_namespaced_pod.side_effect = ApiException(status=404)

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.UNSUPPORTED


def test_swap_reports_disruption_when_the_pod_vanishes_mid_swap() -> None:
    """Evicted between the patch and the restart. Past the patch the old
    container is gone whatever happened next, so this is never UNSUPPORTED."""
    mgr, core_api, _sidecar = _manager(pods=[_pod(digest=OLD_DIGEST)])
    core_api.read_namespaced_pod.side_effect = [
        _pod(digest=OLD_DIGEST),
        ApiException(status=404),
    ]

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.DISRUPTED


def test_kubernetes_never_asks_the_caller_to_provision() -> None:
    """Workspaces are emptyDirs that die with the pod, so they cannot outlive
    a discarded runtime."""
    mgr, _, sidecar = _manager(pods=[_pod(digest=OLD_DIGEST)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is not ImageMoveOutcome.NEEDS_PROVISION


def test_swap_probes_the_sidecar_once_ready_not_on_every_poll() -> None:
    """The sidecar probe is an HTTP call into the pod; polling it while waiting
    for the restart would hit it dozens of times per swap."""
    mgr, _, sidecar = _manager(
        pods=[
            _pod(digest=OLD_DIGEST),
            _pod(digest=OLD_DIGEST),
            _pod(digest=NEW_DIGEST),
        ]
    )

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.MOVED

    assert sidecar.is_healthy.call_count == 1


def test_swap_checks_the_digest_before_sleeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container that has already restarted must not cost a poll interval."""
    slept: list[float] = []
    monkeypatch.setattr(ksm.time, "sleep", lambda seconds: slept.append(seconds))
    mgr, _, sidecar = _manager(pods=[_pod(digest=NEW_DIGEST)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.MOVED
    assert slept == []


def test_swap_requires_the_target_digest_not_merely_a_change() -> None:
    """A status that has not reported yet leaves nothing to compare against, so
    "different from before" would let the *old* image count as a successful swap.
    """
    mgr, _, _sidecar = _manager(
        pods=[_pod(digest=None), _pod(digest=OLD_DIGEST), _pod(digest=OLD_DIGEST)]
    )

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.DISRUPTED


def test_swap_accepts_a_sandbox_already_on_the_target() -> None:
    """Comparing against the target rather than a change also stops a correct
    sandbox from being reported as a failed move and rebuilt for no reason."""
    mgr, _, _sidecar = _manager(pods=[_pod(digest=NEW_DIGEST)])

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.MOVED


def test_swap_gives_the_sidecar_the_rest_of_the_budget() -> None:
    """It restarts on its own schedule and has no readiness probe, so the pod can
    report Ready before the push daemon has bound its port. One probe would send a
    completed swap down the rebuild path."""
    mgr, _, sidecar = _manager(pods=[_pod(digest=NEW_DIGEST)])
    sidecar.is_healthy.side_effect = [False, False, True]

    assert mgr.move_to_image(SANDBOX_ID, TARGET) is ImageMoveOutcome.MOVED
    assert sidecar.is_healthy.call_count == 3
