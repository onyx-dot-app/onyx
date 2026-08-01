"""Recording which release provisioned a sandbox, and reading it back.

Sandbox images are built and released with the application, so a sandbox
stamped with anything but the running release is on the image that shipped with
an earlier one. Both backends stamp the label at creation and read it back from
the one resource they created — nothing consults a registry, a digest, or a
clock.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from docker.errors import APIError, NotFound
from kubernetes import client
from kubernetes.client.rest import ApiException

import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as dsm
import onyx.server.features.build.sandbox.labels as labels_module
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_RELEASE,
    current_release_label,
)

SANDBOX_A = UUID(int=1)


# --- the release label value ------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.2.3", "1.2.3"),
        ("v1.2.3-rc.1", "v1.2.3-rc.1"),
        ("0.0.0-dev", "0.0.0-dev"),
        ("Development", "Development"),
        # PEP 440 local versions and anything else Kubernetes rejects: stamping
        # one would fail the pod create, so the comparison turns off instead.
        ("1.2.3+build.5", None),
        ("-leading-dash", None),
        ("", None),
        ("x" * 64, None),
    ],
)
def test_only_a_legal_label_value_is_used(version: str, expected: str | None) -> None:
    with patch.object(labels_module, "__version__", version):
        assert current_release_label() == expected


def test_both_sides_go_through_one_function() -> None:
    """The stamp and the comparison must never diverge: a version adjusted to be
    a legal label on one side and not the other would read as stale forever."""
    with patch.object(labels_module, "__version__", "9.9.9"):
        assert current_release_label() == "9.9.9"


# --- Kubernetes -------------------------------------------------------------


def _k8s() -> tuple[KubernetesSandboxManager, MagicMock]:
    core_api = MagicMock()
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    return mgr, core_api


def _pod(labels: dict[str, str] | None) -> client.V1Pod:
    return cast(client.V1Pod, SimpleNamespace(metadata=SimpleNamespace(labels=labels)))


def test_k8s_reads_the_release_off_the_pod() -> None:
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.return_value = _pod({LABEL_RELEASE: "1.2.3"})

    assert mgr.provisioned_release(SANDBOX_A) == "1.2.3"


def test_k8s_reads_one_pod_and_never_the_fleet() -> None:
    """Asked only of reap candidates, so it must not scan the namespace."""
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.return_value = _pod({LABEL_RELEASE: "1.2.3"})

    mgr.provisioned_release(SANDBOX_A)

    core_api.list_namespaced_pod.assert_not_called()


def test_k8s_pod_without_the_label_reports_nothing() -> None:
    """Provisioned before this shipped: unknown, so it counts as current and
    ages out on the normal timeout rather than being reaped at once."""
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.return_value = _pod({})

    assert mgr.provisioned_release(SANDBOX_A) is None


def test_k8s_survives_an_unreadable_pod() -> None:
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.side_effect = ApiException(status=404)

    assert mgr.provisioned_release(SANDBOX_A) is None


def test_k8s_stamps_the_release_on_the_pod_it_creates() -> None:
    """The read above is only meaningful if creation writes it."""
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod_template.return_value = SimpleNamespace(
        template=SimpleNamespace(
            metadata=SimpleNamespace(labels={}),
            spec=client.V1PodSpec(containers=[]),
        )
    )

    with (
        patch.object(labels_module, "__version__", "1.2.3"),
        patch.object(KubernetesSandboxManager, "_overlay_dynamic_fields"),
    ):
        pod = mgr._create_sandbox_pod(str(uuid4()), "tenant", 1)

    assert (pod.metadata.labels or {})[LABEL_RELEASE] == "1.2.3"


# --- Docker -----------------------------------------------------------------


def _docker() -> tuple[dsm.DockerSandboxManager, MagicMock]:
    mgr: dsm.DockerSandboxManager = object.__new__(dsm.DockerSandboxManager)
    docker = MagicMock()
    mgr._docker = docker  # type: ignore[attr-defined]
    return mgr, docker


def _container(labels: dict[str, str] | None) -> MagicMock:
    container = MagicMock()
    container.attrs = {"Config": {"Labels": labels}}
    return container


def test_docker_reads_the_release_off_the_container() -> None:
    """``inspect`` nests labels under Config, unlike the ``list`` shape."""
    mgr, docker = _docker()
    docker.containers.get.return_value = _container({LABEL_RELEASE: "1.2.3"})

    assert mgr.provisioned_release(SANDBOX_A) == "1.2.3"


def test_docker_container_without_the_label_reports_nothing() -> None:
    mgr, docker = _docker()
    docker.containers.get.return_value = _container({})

    assert mgr.provisioned_release(SANDBOX_A) is None


def test_docker_survives_a_missing_container() -> None:
    mgr, docker = _docker()
    docker.containers.get.side_effect = NotFound("gone")

    assert mgr.provisioned_release(SANDBOX_A) is None


def test_docker_survives_a_daemon_error() -> None:
    mgr, docker = _docker()
    docker.containers.get.side_effect = APIError("daemon is unwell")

    assert mgr.provisioned_release(SANDBOX_A) is None


def test_docker_stamps_the_release_on_the_container_it_creates() -> None:
    with patch.object(labels_module, "__version__", "1.2.3"):
        labels = dsm.build_sandbox_labels(
            sandbox_id=SANDBOX_A,
            tenant_id="tenant",
            user_id=None,
            provisioning_attempt_number=1,
        )

    assert labels[LABEL_RELEASE] == "1.2.3"
