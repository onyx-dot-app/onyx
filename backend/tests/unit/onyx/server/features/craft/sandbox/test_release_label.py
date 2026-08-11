"""Recording what provisioned a sandbox, and reading it back.

Two stamps at creation: the release (operator-facing provenance, never read
programmatically) and the sandbox image's content identity, which the sweep
reads back and compares. The identity is a hash of the image's build context,
not its tag — a release re-tags the previous image when the context is
unchanged, so the tag moves every deploy while the image itself changes only
when its sources do. Nothing consults a registry, a digest, or a clock.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from docker.errors import APIError, NotFound
from kubernetes import client
from kubernetes.client.rest import ApiException

import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as dsm
import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm
import onyx.server.features.build.sandbox.labels as labels_module
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.labels import (
    LABEL_RELEASE,
    LABEL_SANDBOX_IMAGE,
    current_release_label,
    current_sandbox_image_identity,
)

SANDBOX_A = UUID(int=1)
IDENTITY = "ctx-0123456789abcdef0123"


# --- the release label value ------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.2.3", "1.2.3"),
        ("v1.2.3-rc.1", "v1.2.3-rc.1"),
        ("0.0.0-dev", "0.0.0-dev"),
        ("Development", "Development"),
        # PEP 440 local versions and anything else Kubernetes rejects: stamping
        # one would fail the pod create, so the label is skipped instead.
        ("1.2.3+build.5", None),
        ("-leading-dash", None),
        ("", None),
        ("x" * 64, None),
    ],
)
def test_only_a_legal_label_value_is_used(version: str, expected: str | None) -> None:
    with patch.object(labels_module, "__version__", version):
        assert current_release_label() == expected


# --- the image identity -----------------------------------------------------


@pytest.fixture
def image_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A fake sandbox image build context, with the cache cleared around it."""
    context = tmp_path / "image"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n")
    (context / "entrypoint.sh").write_text("#!/bin/sh\n")
    (context / "entrypoint.sh").chmod(0o644)
    monkeypatch.setattr(labels_module, "_IMAGE_CONTEXT_DIR", context)
    current_sandbox_image_identity.cache_clear()
    yield context
    current_sandbox_image_identity.cache_clear()


def _identity() -> str | None:
    current_sandbox_image_identity.cache_clear()
    return current_sandbox_image_identity()


def test_the_identity_is_a_stable_legal_label_value(image_context: Path) -> None:  # noqa: ARG001
    identity = _identity()

    assert identity is not None
    assert labels_module._LABEL_VALUE.match(identity)
    assert identity == _identity()


def test_the_identity_moves_exactly_when_the_context_does(
    image_context: Path,
) -> None:
    """The tag and the release move every deploy; this must not."""
    before = _identity()

    (image_context / "Dockerfile").write_text("FROM scratch\nRUN true\n")
    changed = _identity()

    (image_context / "Dockerfile").write_text("FROM scratch\n")
    restored = _identity()

    assert before != changed
    assert before == restored


def test_a_chmod_alone_changes_the_identity(image_context: Path) -> None:
    """The build context includes file modes (scripts must stay executable)."""
    before = _identity()

    (image_context / "entrypoint.sh").chmod(0o755)

    assert _identity() != before


def test_runtime_bytecode_is_not_part_of_the_context(image_context: Path) -> None:
    """The hash must see what CI hashes: sources, not what running them left."""
    before = _identity()

    pycache = image_context / "sandbox_daemon" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "daemon.cpython-313.pyc").write_bytes(b"\x00")
    (image_context / "stray.pyc").write_bytes(b"\x00")

    assert _identity() == before


def test_a_missing_context_turns_the_comparison_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(labels_module, "_IMAGE_CONTEXT_DIR", tmp_path / "absent")

    assert _identity() is None
    current_sandbox_image_identity.cache_clear()


def test_the_real_context_produces_an_identity() -> None:
    """Both sides go through this one function against the shipped files; it
    must not come back None on a real checkout."""
    current_sandbox_image_identity.cache_clear()
    try:
        identity = current_sandbox_image_identity()
    finally:
        current_sandbox_image_identity.cache_clear()

    assert identity is not None
    assert identity.startswith("ctx-")


# --- Kubernetes -------------------------------------------------------------


def _k8s() -> tuple[KubernetesSandboxManager, MagicMock]:
    core_api = MagicMock()
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    return mgr, core_api


def _pod(labels: dict[str, str] | None) -> client.V1Pod:
    return cast(client.V1Pod, SimpleNamespace(metadata=SimpleNamespace(labels=labels)))


def test_k8s_reads_the_identity_off_the_pod() -> None:
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.return_value = _pod({LABEL_SANDBOX_IMAGE: IDENTITY})

    assert mgr.provisioned_image_identity(SANDBOX_A) == IDENTITY


def test_k8s_reads_one_pod_and_never_the_fleet() -> None:
    """Asked only of reap candidates, so it must not scan the namespace."""
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.return_value = _pod({LABEL_SANDBOX_IMAGE: IDENTITY})

    mgr.provisioned_image_identity(SANDBOX_A)

    core_api.list_namespaced_pod.assert_not_called()


def test_k8s_pod_without_the_label_reports_nothing() -> None:
    """Provisioned before this shipped: unknown, so it counts as current and
    ages out on the normal timeout rather than being reaped at once."""
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.return_value = _pod({})

    assert mgr.provisioned_image_identity(SANDBOX_A) is None


def test_k8s_survives_an_unreadable_pod() -> None:
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod.side_effect = ApiException(status=404)

    assert mgr.provisioned_image_identity(SANDBOX_A) is None


def test_k8s_stamps_the_identity_and_the_release_on_the_pod_it_creates() -> None:
    """The read above is only meaningful if creation writes it. The release
    rides along for operators; nothing reads it back."""
    mgr, core_api = _k8s()
    core_api.read_namespaced_pod_template.return_value = SimpleNamespace(
        template=SimpleNamespace(
            metadata=SimpleNamespace(labels={}),
            spec=client.V1PodSpec(containers=[]),
        )
    )

    with (
        patch.object(labels_module, "__version__", "1.2.3"),
        patch.object(ksm, "current_sandbox_image_identity", return_value=IDENTITY),
        patch.object(KubernetesSandboxManager, "_overlay_dynamic_fields"),
    ):
        pod = mgr._create_sandbox_pod(str(uuid4()), "tenant", 1)

    labels = pod.metadata.labels or {}
    assert labels[LABEL_SANDBOX_IMAGE] == IDENTITY
    assert labels[LABEL_RELEASE] == "1.2.3"


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


def test_docker_reads_the_identity_off_the_container() -> None:
    """``inspect`` nests labels under Config, unlike the ``list`` shape."""
    mgr, docker = _docker()
    docker.containers.get.return_value = _container({LABEL_SANDBOX_IMAGE: IDENTITY})

    assert mgr.provisioned_image_identity(SANDBOX_A) == IDENTITY


def test_docker_container_without_the_label_reports_nothing() -> None:
    mgr, docker = _docker()
    docker.containers.get.return_value = _container({})

    assert mgr.provisioned_image_identity(SANDBOX_A) is None


def test_docker_survives_a_missing_container() -> None:
    mgr, docker = _docker()
    docker.containers.get.side_effect = NotFound("gone")

    assert mgr.provisioned_image_identity(SANDBOX_A) is None


def test_docker_survives_a_daemon_error() -> None:
    mgr, docker = _docker()
    docker.containers.get.side_effect = APIError("daemon is unwell")

    assert mgr.provisioned_image_identity(SANDBOX_A) is None


def test_docker_stamps_the_identity_and_the_release_on_the_container_it_creates() -> (
    None
):
    with (
        patch.object(labels_module, "__version__", "1.2.3"),
        patch.object(dsm, "current_sandbox_image_identity", return_value=IDENTITY),
    ):
        labels = dsm.build_sandbox_labels(
            sandbox_id=SANDBOX_A,
            tenant_id="tenant",
            user_id=None,
            provisioning_attempt_number=1,
        )

    assert labels[LABEL_SANDBOX_IMAGE] == IDENTITY
    assert labels[LABEL_RELEASE] == "1.2.3"
