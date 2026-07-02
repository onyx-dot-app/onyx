"""Backend-aware constructors for the swappable proxy stores.

``server.py`` calls these instead of instantiating ``K8sSecretCAStore`` /
``K8sInformerLookup`` (or their docker analogues) directly so the proxy boots
correctly under either ``SANDBOX_BACKEND`` value.

Imports of the K8s and docker concrete classes are deferred to the dispatch
call. This keeps each backend's heavy import (``kubernetes`` or ``docker``) out
of the other backend's process import graph, which matters at proxy boot where
the wrong-backend SDK opening config files on import would be wasted work at
best and crash-on-missing-config at worst.
"""

from onyx.sandbox_proxy.ca import CAStore
from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend


def build_ca_store() -> CAStore:
    if SANDBOX_BACKEND is SandboxBackend.KUBERNETES:
        from onyx.sandbox_proxy.ca_k8s import K8sSecretCAStore

        return K8sSecretCAStore()
    if SANDBOX_BACKEND is SandboxBackend.DOCKER:
        from onyx.sandbox_proxy.ca_docker import FileCAStore

        return FileCAStore()
    raise RuntimeError(f"Unsupported SANDBOX_BACKEND={SANDBOX_BACKEND!r}.")


def build_ip_lookup() -> SandboxIPLookup:
    if SANDBOX_BACKEND is SandboxBackend.KUBERNETES:
        from onyx.sandbox_proxy.identity_k8s import K8sInformerLookup

        return K8sInformerLookup()
    if SANDBOX_BACKEND is SandboxBackend.DOCKER:
        from onyx.sandbox_proxy.identity_docker import DockerEventsLookup

        return DockerEventsLookup()
    raise RuntimeError(f"Unsupported SANDBOX_BACKEND={SANDBOX_BACKEND!r}.")
