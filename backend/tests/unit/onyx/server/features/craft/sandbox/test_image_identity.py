"""Unit tests for sandbox image-identity detection.

Sandbox pods/containers are owned by no controller, so a deploy leaves live
ones on the old image. These tests cover the comparison that detects it: the
staleness precedence rules, and the per-backend extraction that feeds them.
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
from onyx.server.features.build.sandbox.models import SandboxImageIdentity

SANDBOX_ID = UUID("12345678-1234-1234-1234-1234567890ab")

TAG_REF = "onyxdotapp/sandbox:v1.2.3"
NEW_TAG_REF = "onyxdotapp/sandbox:v1.3.0"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _identity(**overrides: Any) -> SandboxImageIdentity:
    base: dict[str, Any] = {
        "running_ref": TAG_REF,
        "running_digest": None,
        "desired_ref": TAG_REF,
        "desired_digest": None,
    }
    return SandboxImageIdentity(**{**base, **overrides})


# --- staleness precedence ---------------------------------------------------


def test_matching_refs_are_not_stale() -> None:
    assert _identity().is_stale is False


def test_changed_ref_is_stale() -> None:
    assert _identity(desired_ref=NEW_TAG_REF).is_stale is True


def test_digests_win_over_refs() -> None:
    """A retag onto identical content must not cycle anyone's pod: the release
    pipeline content-addresses the image and re-tags the same manifest when the
    build context is unchanged, so most deploys land here."""
    identity = _identity(
        running_ref=TAG_REF,
        running_digest=DIGEST_A,
        desired_ref=NEW_TAG_REF,
        desired_digest=DIGEST_A,
    )
    assert identity.digest_comparable is True
    assert identity.is_stale is False


def test_same_ref_different_digest_is_stale() -> None:
    """The mutable-tag case: `:latest` repointed at new content."""
    identity = _identity(running_digest=DIGEST_A, desired_digest=DIGEST_B)
    assert identity.is_stale is True


def test_repository_prefix_is_stripped_from_digests() -> None:
    """A K8s imageID may carry a repository prefix while a Docker image ID
    never does; the bare digest is the only comparable part."""
    identity = _identity(
        running_digest=f"docker.io/onyxdotapp/sandbox@{DIGEST_A}",
        desired_digest=DIGEST_A,
    )
    assert identity.running_digest == DIGEST_A
    assert identity.is_stale is False


def test_unknown_running_identity_is_not_stale() -> None:
    """Recycling costs a user their pod, so it takes positive evidence."""
    assert _identity(running_ref=None, desired_ref=NEW_TAG_REF).is_stale is False


def test_one_sided_digest_falls_back_to_refs() -> None:
    identity = _identity(running_digest=DIGEST_A, desired_ref=NEW_TAG_REF)
    assert identity.digest_comparable is False
    assert identity.is_stale is True


# --- Kubernetes extraction --------------------------------------------------


def _k8s_manager(core_api: MagicMock) -> KubernetesSandboxManager:
    """Construct a manager without _initialize (which needs a K8s config)."""
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    return mgr


def _pod(spec_image: str, status_image_id: str | None) -> client.V1Pod:
    pod = SimpleNamespace(
        spec=SimpleNamespace(
            containers=[SimpleNamespace(name="sandbox", image=spec_image)],
            init_containers=[],
        ),
        status=SimpleNamespace(
            container_statuses=[
                SimpleNamespace(
                    name="sandbox",
                    image=f"docker.io/{spec_image}",
                    image_id=status_image_id,
                    ready=True,
                    state=SimpleNamespace(running=object(), terminated=None),
                )
            ]
        ),
    )
    return cast(client.V1Pod, pod)


def _podtemplate(image: str) -> SimpleNamespace:
    return SimpleNamespace(
        template=SimpleNamespace(
            spec=SimpleNamespace(
                containers=[SimpleNamespace(name="sandbox", image=image)],
                init_containers=[],
            )
        )
    )


def test_k8s_running_ref_comes_from_spec_not_status() -> None:
    """The status ref is the runtime's normalized form (`docker.io/`-prefixed)
    and would never compare equal to the PodTemplate's."""
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(TAG_REF)
    mgr = _k8s_manager(core_api)

    identity = mgr._image_identity(_pod(TAG_REF, None))

    assert identity is not None
    assert identity.running_ref == TAG_REF
    assert identity.is_stale is False


def test_k8s_detects_podtemplate_image_change() -> None:
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(NEW_TAG_REF)
    mgr = _k8s_manager(core_api)

    identity = mgr._image_identity(_pod(TAG_REF, None))

    assert identity is not None
    assert identity.is_stale is True


def test_k8s_unpinned_ref_yields_no_desired_digest() -> None:
    """The shape every real pod has: the runtime reports a digest, the
    deployment pins none (``global.version`` and SANDBOX_CONTAINER_IMAGE both
    default to a mutable tag).

    Nothing on the desired side is digest-grade here, so the comparison has to
    fall back to refs. Letting the tag stand in for a digest would compare
    ``sha256:…`` against ``…:latest`` and report every sandbox in the fleet as
    permanently stale.
    """
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(TAG_REF)
    mgr = _k8s_manager(core_api)

    identity = mgr._image_identity(
        _pod(TAG_REF, f"docker.io/onyxdotapp/sandbox@{DIGEST_A}")
    )

    assert identity is not None
    assert identity.desired_digest is None
    assert identity.digest_comparable is False
    assert identity.is_stale is False


def test_k8s_unpinned_ref_change_is_still_detected() -> None:
    """Falling back to refs must not blind the check to a tag that moved."""
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(NEW_TAG_REF)
    mgr = _k8s_manager(core_api)

    identity = mgr._image_identity(
        _pod(TAG_REF, f"docker.io/onyxdotapp/sandbox@{DIGEST_A}")
    )

    assert identity is not None
    assert identity.is_stale is True


def test_k8s_compares_digests_when_the_deployment_pins_one() -> None:
    pinned = f"onyxdotapp/sandbox@{DIGEST_A}"
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(pinned)
    mgr = _k8s_manager(core_api)

    identity = mgr._image_identity(
        _pod(TAG_REF, f"docker.io/onyxdotapp/sandbox@{DIGEST_A}")
    )

    assert identity is not None
    assert identity.digest_comparable is True
    assert identity.is_stale is False


def test_k8s_unreadable_podtemplate_yields_no_identity() -> None:
    """An unreadable PodTemplate must degrade to "unknown", not fail the
    health check it shares a read with."""
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.side_effect = ApiException(status=403)
    mgr = _k8s_manager(core_api)

    assert mgr._image_identity(_pod(TAG_REF, None)) is None


def test_k8s_desired_image_is_cached_across_calls() -> None:
    """This runs on the health path, which is on the provisioning hot path."""
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(TAG_REF)
    mgr = _k8s_manager(core_api)

    for _ in range(3):
        mgr._image_identity(_pod(TAG_REF, None))

    assert core_api.read_namespaced_pod_template.call_count == 1


def test_k8s_runtime_state_reads_the_pod_once() -> None:
    """Identity has to ride the existing read or it doubles the API calls."""
    core_api = MagicMock()
    core_api.read_namespaced_pod.return_value = _pod(TAG_REF, None)
    core_api.read_namespaced_pod_template.return_value = _podtemplate(NEW_TAG_REF)
    mgr = _k8s_manager(core_api)
    mgr._sidecar_client = MagicMock()  # type: ignore[attr-defined]
    mgr._sidecar_client.is_healthy.return_value = True

    state = mgr.get_runtime_state(SANDBOX_ID, timeout=1.0)

    assert core_api.read_namespaced_pod.call_count == 1
    assert state.healthy is True
    assert state.image is not None and state.image.is_stale is True


def test_k8s_missing_pod_reports_unknown_identity() -> None:
    core_api = MagicMock()
    core_api.read_namespaced_pod.side_effect = ApiException(status=404)
    mgr = _k8s_manager(core_api)

    state = mgr.get_runtime_state(SANDBOX_ID, timeout=1.0)

    assert state.healthy is False
    assert state.image is None


# --- Docker extraction ------------------------------------------------------


def _docker_manager(image: str) -> tuple[dsm.DockerSandboxManager, MagicMock]:
    mgr: dsm.DockerSandboxManager = object.__new__(dsm.DockerSandboxManager)
    docker = MagicMock()
    mgr._docker = docker  # type: ignore[attr-defined]
    mgr._image = image  # type: ignore[attr-defined]
    mgr._image_checked = False  # type: ignore[attr-defined]
    mgr._image_check_lock = threading.Lock()  # type: ignore[attr-defined]
    return mgr, docker


def _container(config_image: str, image_id: str) -> MagicMock:
    container = MagicMock()
    container.attrs = {"Config": {"Image": config_image}, "Image": image_id}
    return container


def test_docker_detects_repointed_mutable_tag() -> None:
    """Docker image IDs are local on both sides, so `:latest` moving to new
    content is caught exactly — no digest pin required."""
    mgr, docker = _docker_manager("onyxdotapp/sandbox:latest")
    docker.images.get.return_value = SimpleNamespace(id=DIGEST_B)

    identity = mgr._image_identity(_container("onyxdotapp/sandbox:latest", DIGEST_A))

    assert identity.digest_comparable is True
    assert identity.is_stale is True


def test_docker_same_image_is_not_stale() -> None:
    mgr, docker = _docker_manager("onyxdotapp/sandbox:latest")
    docker.images.get.return_value = SimpleNamespace(id=DIGEST_A)

    identity = mgr._image_identity(_container("onyxdotapp/sandbox:latest", DIGEST_A))

    assert identity.is_stale is False


def test_docker_unpulled_image_falls_back_to_refs() -> None:
    mgr, docker = _docker_manager(NEW_TAG_REF)
    docker.images.get.side_effect = NotFound("absent")

    identity = mgr._image_identity(_container(TAG_REF, DIGEST_A))

    assert identity.digest_comparable is False
    assert identity.is_stale is True


@pytest.mark.parametrize("missing_container", [True, False])
def test_docker_runtime_state_tracks_container_presence(
    missing_container: bool,
) -> None:
    mgr, docker = _docker_manager("onyxdotapp/sandbox:latest")
    docker.images.get.return_value = SimpleNamespace(id=DIGEST_A)

    container = _container("onyxdotapp/sandbox:latest", DIGEST_A)
    container.attrs["State"] = {"Status": "running"}
    docker.containers.get.side_effect = (
        NotFound("absent") if missing_container else None
    )
    docker.containers.get.return_value = None if missing_container else container

    state = mgr.get_runtime_state(SANDBOX_ID, timeout=1.0)

    assert state.healthy is not missing_container
    assert (state.image is None) is missing_container


# --- fleet scan -------------------------------------------------------------
#
# "Which sandboxes are on a superseded image" is derived from what is actually
# running rather than recorded when a new image lands, so it needs no
# bookkeeping to stay true. That only pays off if the whole fleet costs one
# backend call, which is what these pin.


def _labelled_pod(sandbox_id: str, spec_image: str) -> SimpleNamespace:
    pod = _pod(spec_image, None)
    pod.metadata = SimpleNamespace(  # type: ignore[attr-defined]
        name=f"sandbox-{sandbox_id[:8]}",
        labels={"onyx.app/sandbox-id": sandbox_id},
    )
    return cast(SimpleNamespace, pod)


def test_k8s_fleet_scan_costs_one_list_call() -> None:
    ids = [str(UUID(int=i)) for i in range(3)]
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(NEW_TAG_REF)
    mgr = _k8s_manager(core_api)
    core_api.list_namespaced_pod.return_value = SimpleNamespace(
        items=[_labelled_pod(i, TAG_REF) for i in ids]
    )

    identities = mgr.list_live_sandbox_images()

    assert set(identities) == {UUID(i) for i in ids}
    assert all(identity.is_stale for identity in identities.values())
    # One list for the pods, one PodTemplate read shared across all of them.
    assert core_api.list_namespaced_pod.call_count == 1
    assert core_api.read_namespaced_pod_template.call_count == 1


def test_k8s_fleet_scan_separates_current_from_superseded() -> None:
    current, stale = str(UUID(int=1)), str(UUID(int=2))
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(NEW_TAG_REF)
    mgr = _k8s_manager(core_api)
    core_api.list_namespaced_pod.return_value = SimpleNamespace(
        items=[
            _labelled_pod(current, NEW_TAG_REF),
            _labelled_pod(stale, TAG_REF),
        ]
    )

    identities = mgr.list_live_sandbox_images()

    assert identities[UUID(current)].is_stale is False
    assert identities[UUID(stale)].is_stale is True


def test_k8s_fleet_scan_skips_pods_without_a_usable_id() -> None:
    """A pod that cannot be tied back to a sandbox row is not actionable, and a
    malformed label must not take the whole scan down with it."""
    good = str(UUID(int=7))
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(TAG_REF)
    mgr = _k8s_manager(core_api)
    unlabelled = _pod(TAG_REF, None)
    unlabelled.metadata = SimpleNamespace(name="orphan", labels={})  # type: ignore[attr-defined]
    core_api.list_namespaced_pod.return_value = SimpleNamespace(
        items=[
            unlabelled,
            _labelled_pod("not-a-uuid", TAG_REF),
            _labelled_pod(good, TAG_REF),
        ]
    )

    assert set(mgr.list_live_sandbox_images()) == {UUID(good)}


def test_k8s_fleet_scan_reports_nothing_when_the_desired_image_is_unknown() -> None:
    """An unreadable PodTemplate must not make the fleet look stale."""
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.side_effect = ApiException(status=403)
    mgr = _k8s_manager(core_api)
    core_api.list_namespaced_pod.return_value = SimpleNamespace(
        items=[_labelled_pod(str(UUID(int=1)), TAG_REF)]
    )

    assert mgr.list_live_sandbox_images() == {}


def test_k8s_fleet_scan_survives_an_unlistable_namespace() -> None:
    core_api = MagicMock()
    core_api.read_namespaced_pod_template.return_value = _podtemplate(TAG_REF)
    mgr = _k8s_manager(core_api)
    core_api.list_namespaced_pod.side_effect = ApiException(status=403)

    assert mgr.list_live_sandbox_images() == {}


def _listed_container(sandbox_id: str, image: str, image_id: str) -> MagicMock:
    container = MagicMock()
    container.name = f"sandbox-{sandbox_id[:8]}"
    # List shape, not inspect shape: ref and resolved ID at the top level.
    container.attrs = {
        "Image": image,
        "ImageID": image_id,
        "Labels": {"onyx.app/sandbox-id": sandbox_id},
    }
    return container


def test_docker_fleet_scan_uses_the_list_shape() -> None:
    """`list` reports Image/ImageID at the top level while `inspect` nests the
    ref under Config; reading the wrong pair yields a bogus comparison."""
    sandbox_id = str(UUID(int=3))
    mgr, docker = _docker_manager("onyxdotapp/sandbox:latest")
    docker.images.get.return_value = SimpleNamespace(id=DIGEST_B)
    docker.containers.list.return_value = [
        _listed_container(sandbox_id, "onyxdotapp/sandbox:latest", DIGEST_A)
    ]

    identities = mgr.list_live_sandbox_images()

    assert set(identities) == {UUID(sandbox_id)}
    identity = identities[UUID(sandbox_id)]
    assert identity.running_digest == DIGEST_A
    assert identity.is_stale is True


def test_docker_fleet_scan_includes_stopped_containers() -> None:
    """A stopped container is restarted rather than recreated, so one built from
    a superseded image would come back on it."""
    mgr, docker = _docker_manager("onyxdotapp/sandbox:latest")
    docker.images.get.return_value = SimpleNamespace(id=DIGEST_B)
    docker.containers.list.return_value = []

    mgr.list_live_sandbox_images()

    assert docker.containers.list.call_args.kwargs["all"] is True


def test_docker_fleet_scan_survives_a_daemon_error() -> None:
    mgr, docker = _docker_manager("onyxdotapp/sandbox:latest")
    docker.containers.list.side_effect = APIError("daemon is unwell")

    assert mgr.list_live_sandbox_images() == {}
