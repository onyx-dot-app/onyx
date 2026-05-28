from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.sandbox_proxy import backend as backend_mod
from onyx.server.features.build.configs import SandboxBackend

# ``build_ca_store`` and ``build_ip_lookup`` instantiate the concrete K8s /
# docker classes, which require live config (kube config / docker socket) on
# construction. Patch the constructors to no-op MagicMocks so we exercise the
# dispatch logic without dragging in those dependencies.


def _patch_ctors(*, k8s_ca=None, docker_ca=None, k8s_ip=None, docker_ip=None):
    return [
        patch(
            "onyx.sandbox_proxy.ca_k8s.K8sSecretCAStore",
            return_value=k8s_ca or MagicMock(),
        ),
        patch(
            "onyx.sandbox_proxy.ca_docker.FileCAStore",
            return_value=docker_ca or MagicMock(),
        ),
        patch(
            "onyx.sandbox_proxy.identity_k8s.K8sInformerLookup",
            return_value=k8s_ip or MagicMock(),
        ),
        patch(
            "onyx.sandbox_proxy.identity_docker.DockerEventsLookup",
            return_value=docker_ip or MagicMock(),
        ),
    ]


def test_build_ca_store_kubernetes_dispatches_k8s_store() -> None:
    expected = MagicMock()
    patches = _patch_ctors(k8s_ca=expected)
    for p in patches:
        p.start()
    try:
        with patch.object(backend_mod, "SANDBOX_BACKEND", SandboxBackend.KUBERNETES):
            assert backend_mod.build_ca_store() is expected
    finally:
        for p in patches:
            p.stop()


def test_build_ca_store_docker_dispatches_file_store() -> None:
    expected = MagicMock()
    patches = _patch_ctors(docker_ca=expected)
    for p in patches:
        p.start()
    try:
        with patch.object(backend_mod, "SANDBOX_BACKEND", SandboxBackend.DOCKER):
            assert backend_mod.build_ca_store() is expected
    finally:
        for p in patches:
            p.stop()


def test_build_ip_lookup_kubernetes_dispatches_informer() -> None:
    expected = MagicMock()
    patches = _patch_ctors(k8s_ip=expected)
    for p in patches:
        p.start()
    try:
        with patch.object(backend_mod, "SANDBOX_BACKEND", SandboxBackend.KUBERNETES):
            assert backend_mod.build_ip_lookup() is expected
    finally:
        for p in patches:
            p.stop()


def test_build_ip_lookup_docker_dispatches_events_lookup() -> None:
    expected = MagicMock()
    patches = _patch_ctors(docker_ip=expected)
    for p in patches:
        p.start()
    try:
        with patch.object(backend_mod, "SANDBOX_BACKEND", SandboxBackend.DOCKER):
            assert backend_mod.build_ip_lookup() is expected
    finally:
        for p in patches:
            p.stop()


def test_build_ca_store_raises_on_unknown_backend() -> None:
    sentinel = object()
    with patch.object(backend_mod, "SANDBOX_BACKEND", sentinel):
        with pytest.raises(RuntimeError, match="unsupported SANDBOX_BACKEND"):
            backend_mod.build_ca_store()


def test_build_ip_lookup_raises_on_unknown_backend() -> None:
    sentinel = object()
    with patch.object(backend_mod, "SANDBOX_BACKEND", sentinel):
        with pytest.raises(RuntimeError, match="unsupported SANDBOX_BACKEND"):
            backend_mod.build_ip_lookup()
