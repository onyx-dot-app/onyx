from unittest.mock import MagicMock, patch

import pytest

from onyx.sandbox_proxy.certificate_authority import bootstrap as ca_mod
from onyx.sandbox_proxy.sandbox_identity import resolution as identity_mod
from onyx.server.features.build.configs import SandboxBackend

# Each test patches only the single constructor the dispatch branch is expected
# to hit. The unpatched branch's concrete class would require live config (kube
# config / docker socket) on construction, so we never let dispatch reach it.


def test_build_ca_store_kubernetes_dispatches_k8s_store() -> None:
    expected = MagicMock()
    with (
        patch(
            "onyx.sandbox_proxy.certificate_authority.kubernetes.K8sSecretCAStore",
            return_value=expected,
        ),
        patch.object(ca_mod, "SANDBOX_BACKEND", SandboxBackend.KUBERNETES),
    ):
        assert ca_mod.build_ca_store() is expected


def test_build_ca_store_docker_dispatches_file_store() -> None:
    expected = MagicMock()
    with (
        patch(
            "onyx.sandbox_proxy.certificate_authority.docker.FileCAStore",
            return_value=expected,
        ),
        patch.object(ca_mod, "SANDBOX_BACKEND", SandboxBackend.DOCKER),
    ):
        assert ca_mod.build_ca_store() is expected


def test_build_ip_lookup_kubernetes_dispatches_informer() -> None:
    expected = MagicMock()
    with (
        patch(
            "onyx.sandbox_proxy.sandbox_identity.kubernetes.K8sInformerLookup",
            return_value=expected,
        ),
        patch.object(identity_mod, "SANDBOX_BACKEND", SandboxBackend.KUBERNETES),
    ):
        assert identity_mod.build_ip_lookup() is expected


def test_build_ip_lookup_docker_dispatches_events_lookup() -> None:
    expected = MagicMock()
    with (
        patch(
            "onyx.sandbox_proxy.sandbox_identity.docker.DockerEventsLookup",
            return_value=expected,
        ),
        patch.object(identity_mod, "SANDBOX_BACKEND", SandboxBackend.DOCKER),
    ):
        assert identity_mod.build_ip_lookup() is expected


def test_build_ca_store_raises_on_unknown_backend() -> None:
    sentinel = object()
    with patch.object(ca_mod, "SANDBOX_BACKEND", sentinel):
        with pytest.raises(RuntimeError, match="Unsupported SANDBOX_BACKEND"):
            ca_mod.build_ca_store()


def test_build_ip_lookup_raises_on_unknown_backend() -> None:
    sentinel = object()
    with patch.object(identity_mod, "SANDBOX_BACKEND", sentinel):
        with pytest.raises(RuntimeError, match="Unsupported SANDBOX_BACKEND"):
            identity_mod.build_ip_lookup()
