"""Establishing which image sandboxes should run, and which are behind.

The load-bearing subtlety: "should run" has to mean *and already downloaded*.
Restarting a sandbox onto an image its host lacks is worse than leaving it a
version behind, so anything unconfirmed declines.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from docker.errors import APIError, NotFound
from kubernetes import client
from kubernetes.client.rest import ApiException

import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as dsm
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import sandbox_image_digest

TAG_REF = "docker.io/onyxdotapp/sandbox:latest"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
SANDBOX_A = UUID(int=1)
SANDBOX_B = UUID(int=2)


# --- digest normalisation ---------------------------------------------------


@pytest.mark.parametrize(
    "reported,expected",
    [
        (f"docker.io/onyxdotapp/sandbox@{DIGEST_A}", DIGEST_A),
        (DIGEST_A, DIGEST_A),
        (None, None),
        ("", None),
    ],
)
def test_only_the_digest_is_comparable(
    reported: str | None, expected: str | None
) -> None:
    """Runtimes differ on prefixing the repository; only the digest is shared."""
    assert sandbox_image_digest(reported) == expected


# --- Kubernetes: the target comes from the prepuller ------------------------


def _prepuller_pod(ref: str, image_id: str | None) -> client.V1Pod:
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="prepuller-abc", labels={}),
        spec=SimpleNamespace(containers=[SimpleNamespace(name="prepuller", image=ref)]),
        status=SimpleNamespace(
            container_statuses=[
                SimpleNamespace(name="prepuller", image=ref, image_id=image_id)
            ],
            init_container_statuses=[],
        ),
    )
    return cast(client.V1Pod, pod)


def _sandbox_pod(sandbox_id: UUID | str, image_id: str | None) -> client.V1Pod:
    pod = SimpleNamespace(
        metadata=SimpleNamespace(
            name="sandbox-abc", labels={"onyx.app/sandbox-id": str(sandbox_id)}
        ),
        spec=SimpleNamespace(
            containers=[SimpleNamespace(name="sandbox", image=TAG_REF)]
        ),
        status=SimpleNamespace(
            container_statuses=[
                SimpleNamespace(name="sandbox", image=TAG_REF, image_id=image_id)
            ],
            init_container_statuses=[],
        ),
    )
    return cast(client.V1Pod, pod)


def _k8s(prepullers: list[client.V1Pod], sandboxes: list[client.V1Pod] | None = None):
    core_api = MagicMock()

    def listed(*_a: Any, **kwargs: Any) -> SimpleNamespace:
        selector = kwargs.get("label_selector", "")
        items = prepullers if "prepuller" in selector else (sandboxes or [])
        return SimpleNamespace(items=items)

    core_api.list_namespaced_pod.side_effect = listed
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    mgr._image_target_cache = None  # type: ignore[attr-defined]
    return mgr, core_api


def test_agreed_prepull_gives_a_digest_pinned_target() -> None:
    """Agreement is what confirms the image is current *and* present. Pinned,
    because patching a tag onto a pod already running it is not a change."""
    mgr, _ = _k8s(
        [_prepuller_pod(TAG_REF, f"docker.io/onyxdotapp/sandbox@{DIGEST_A}")] * 3
    )

    target = mgr.get_image_state().target

    assert target is not None
    assert target.digest == DIGEST_A
    assert target.ref == f"docker.io/onyxdotapp/sandbox@{DIGEST_A}"


def test_bare_digest_report_is_repaired_into_a_pinned_ref() -> None:
    """A runtime reporting a bare digest gets its repository from the ref."""
    mgr, _ = _k8s([_prepuller_pod(TAG_REF, DIGEST_A)])

    target = mgr.get_image_state().target

    assert target is not None
    assert target.ref == f"docker.io/onyxdotapp/sandbox@{DIGEST_A}"


def test_disagreeing_nodes_yield_no_target() -> None:
    """Mid-rollout: acting now sends some sandboxes to an image they lack."""
    mgr, _ = _k8s(
        [
            _prepuller_pod(TAG_REF, DIGEST_A),
            _prepuller_pod(TAG_REF, DIGEST_B),
        ]
    )

    assert mgr.get_image_state().target is None


def test_node_still_pulling_yields_no_target() -> None:
    """No reported image ID means that node's pull is unfinished."""
    mgr, _ = _k8s([_prepuller_pod(TAG_REF, DIGEST_A), _prepuller_pod(TAG_REF, None)])

    assert mgr.get_image_state().target is None


def test_absent_prepuller_yields_no_target() -> None:
    """sandboxImagePrepull.enabled=false: nothing can vouch for a node."""
    mgr, _ = _k8s([])

    assert mgr.get_image_state().target is None


def test_unreadable_prepuller_yields_no_target() -> None:
    mgr, core_api = _k8s([])
    core_api.list_namespaced_pod.side_effect = ApiException(status=403)

    assert mgr.get_image_state().target is None


def test_target_is_cached_across_calls() -> None:
    """Read every pass. The fleet read is deliberately not cached: a stale view
    of what sandboxes run would produce wrong work."""
    mgr, core_api = _k8s([_prepuller_pod(TAG_REF, DIGEST_A)])

    for _ in range(3):
        mgr.get_image_state()

    prepuller_reads = [
        call
        for call in core_api.list_namespaced_pod.call_args_list
        if "prepuller" in call.kwargs.get("label_selector", "")
    ]
    assert len(prepuller_reads) == 1


# --- Kubernetes: what the fleet is running ----------------------------------


def test_fleet_digests_come_from_one_list_call() -> None:
    mgr, core_api = _k8s(
        [_prepuller_pod(TAG_REF, DIGEST_B)],
        [_sandbox_pod(SANDBOX_A, DIGEST_A), _sandbox_pod(SANDBOX_B, DIGEST_B)],
    )

    digests = mgr.get_image_state().live_digests

    assert digests == {SANDBOX_A: DIGEST_A, SANDBOX_B: DIGEST_B}
    # One list for the fleet, one for the prepuller — not a call per sandbox.
    assert core_api.list_namespaced_pod.call_count == 2


def test_fleet_digests_skip_pods_that_cannot_be_tied_to_a_sandbox() -> None:
    """A malformed label is not actionable and must not fail the whole scan."""
    mgr, _ = _k8s(
        [],
        [
            _sandbox_pod("not-a-uuid", DIGEST_A),
            _sandbox_pod(SANDBOX_B, DIGEST_B),
        ],
    )

    assert mgr.get_image_state().live_digests == {SANDBOX_B: DIGEST_B}


def test_fleet_digests_omit_pods_that_have_not_reported() -> None:
    """A pod still starting is already on the image it was created with."""
    mgr, _ = _k8s([], [_sandbox_pod(SANDBOX_A, None)])

    assert mgr.get_image_state().live_digests == {}


def test_fleet_digests_survive_an_unlistable_namespace() -> None:
    mgr, core_api = _k8s([], [])
    core_api.list_namespaced_pod.side_effect = ApiException(status=403)

    assert mgr.get_image_state().live_digests == {}


# --- Docker -----------------------------------------------------------------


def _docker(image: str = "onyxdotapp/sandbox:latest"):
    mgr: dsm.DockerSandboxManager = object.__new__(dsm.DockerSandboxManager)
    docker = MagicMock()
    mgr._docker = docker  # type: ignore[attr-defined]
    mgr._image = image  # type: ignore[attr-defined]
    mgr._image_checked = False  # type: ignore[attr-defined]
    mgr._image_check_lock = threading.Lock()  # type: ignore[attr-defined]
    # Resolvable by default: the state read always resolves a target alongside
    # the fleet, so a test about the fleet shouldn't have to care.
    docker.images.get.return_value = SimpleNamespace(id=DIGEST_B)
    docker.containers.list.return_value = []
    return mgr, docker


def _listed_container(sandbox_id: UUID | str, image_id: str) -> MagicMock:
    container = MagicMock()
    container.name = "sandbox-abc"
    container.attrs = {
        "Image": "onyxdotapp/sandbox:latest",
        "ImageID": image_id,
        "Labels": {"onyx.app/sandbox-id": str(sandbox_id)},
    }
    return container


def test_docker_target_is_the_local_image() -> None:
    """Local IDs on both sides catch a repointed tag without pinning."""
    mgr, docker = _docker()
    docker.images.get.return_value = SimpleNamespace(id=DIGEST_B)

    target = mgr.get_image_state().target

    assert target is not None
    assert target.digest == DIGEST_B
    assert target.ref == "onyxdotapp/sandbox:latest"


def test_docker_unpulled_image_yields_no_target() -> None:
    """An ID resolves only after a pull, so mid-pull declines for free."""
    mgr, docker = _docker()
    docker.images.get.side_effect = NotFound("absent")

    assert mgr.get_image_state().target is None


def test_docker_fleet_digests_use_the_list_shape() -> None:
    """`list` reports ImageID; `inspect` nests the ref under Config."""
    mgr, docker = _docker()
    docker.containers.list.return_value = [_listed_container(SANDBOX_A, DIGEST_A)]

    assert mgr.get_image_state().live_digests == {SANDBOX_A: DIGEST_A}
    assert docker.containers.list.call_args.kwargs["all"] is True


def test_docker_fleet_digests_survive_a_daemon_error() -> None:
    mgr, docker = _docker()
    docker.containers.list.side_effect = APIError("daemon is unwell")

    assert mgr.get_image_state().live_digests == {}


# --- comparing the two ------------------------------------------------------


def test_state_names_only_the_sandboxes_that_are_behind() -> None:
    mgr, _ = _k8s(
        [_prepuller_pod(TAG_REF, DIGEST_B)],
        [_sandbox_pod(SANDBOX_A, DIGEST_A), _sandbox_pod(SANDBOX_B, DIGEST_B)],
    )

    assert mgr.get_image_state().stale_sandbox_ids() == {SANDBOX_A}


def test_state_produces_no_work_without_a_target() -> None:
    """An unconfirmed image must not make the whole fleet look stale."""
    mgr, _ = _k8s([], [_sandbox_pod(SANDBOX_A, DIGEST_A)])

    state = mgr.get_image_state()

    assert state.target is None
    assert state.stale_sandbox_ids() == set()
