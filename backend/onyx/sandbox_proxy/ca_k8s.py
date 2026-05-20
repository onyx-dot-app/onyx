"""Kubernetes implementation of the CA persistence layer.

The Secret in the proxy's namespace is the source of truth. A
ConfigMap in the sandbox namespace mirrors only the public cert so
sandbox init containers can mount it (K8s does not allow
cross-namespace ConfigMap mounts).
"""

import base64
import binascii
import time

from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.sandbox_proxy.ca import CAStore
from onyx.sandbox_proxy.ca import CAStoreConflictError
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_CA_CONFIGMAP
from onyx.server.features.build.configs import SANDBOX_PROXY_CA_SECRET
from onyx.server.features.build.configs import SANDBOX_PROXY_NAMESPACE
from onyx.server.features.build.sandbox.kubernetes.k8s_client import load_kube_config
from onyx.utils.logger import setup_logger

logger = setup_logger()


_CA_CERT_SECRET_KEY = "ca.crt"
_CA_KEY_SECRET_KEY = "ca.key"
_CA_CERT_CONFIGMAP_KEY = "ca.crt"

_CONFIGMAP_REPLACE_MAX_ATTEMPTS = 5
_CONFIGMAP_REPLACE_MAX_BACKOFF = 1.6


def _decode_cert_for_configmap(cert_pem: bytes) -> str:
    try:
        return cert_pem.decode("ascii")
    except UnicodeDecodeError as e:
        raise RuntimeError(f"proxy CA cert is not ASCII-encodable PEM: {e}") from e


class K8sSecretCAStore(CAStore):
    def __init__(
        self,
        core_api: client.CoreV1Api | None = None,
        proxy_namespace: str = SANDBOX_PROXY_NAMESPACE,
        sandbox_namespace: str = SANDBOX_NAMESPACE,
        secret_name: str = SANDBOX_PROXY_CA_SECRET,
        configmap_name: str = SANDBOX_PROXY_CA_CONFIGMAP,
    ) -> None:
        if core_api is None:
            load_kube_config()
            core_api = client.CoreV1Api()
        self._core = core_api
        self._proxy_ns = proxy_namespace
        self._sandbox_ns = sandbox_namespace
        self._secret_name = secret_name
        self._configmap_name = configmap_name

    def load(self) -> tuple[bytes, bytes] | None:
        try:
            secret = self._core.read_namespaced_secret(
                name=self._secret_name, namespace=self._proxy_ns
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise

        data = secret.data or {}
        if _CA_CERT_SECRET_KEY not in data or _CA_KEY_SECRET_KEY not in data:
            # Regenerating would invalidate any sandbox that's already
            # mounted the old ConfigMap. Fail loud instead.
            raise RuntimeError(
                f"Secret {self._proxy_ns}/{self._secret_name} exists but "
                f"is missing {_CA_CERT_SECRET_KEY} or {_CA_KEY_SECRET_KEY}"
            )

        try:
            cert_pem = base64.b64decode(data[_CA_CERT_SECRET_KEY])
            key_pem = base64.b64decode(data[_CA_KEY_SECRET_KEY])
        except (binascii.Error, ValueError) as e:
            raise RuntimeError(
                f"Secret {self._proxy_ns}/{self._secret_name} has malformed "
                f"base64 data: {e}"
            ) from e

        # Re-project on every load so a deleted ConfigMap self-heals
        # on the next proxy restart.
        self._ensure_configmap(cert_pem)

        return cert_pem, key_pem

    def persist(self, cert_pem: bytes, key_pem: bytes) -> None:
        secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            type="Opaque",
            metadata=client.V1ObjectMeta(
                name=self._secret_name,
                namespace=self._proxy_ns,
                labels={
                    "app.kubernetes.io/managed-by": "onyx",
                    "app.kubernetes.io/component": "sandbox-proxy",
                    "onyx.app/resource": "sandbox-proxy-ca",
                },
            ),
            data={
                _CA_CERT_SECRET_KEY: base64.b64encode(cert_pem).decode(),
                _CA_KEY_SECRET_KEY: base64.b64encode(key_pem).decode(),
            },
        )

        try:
            self._core.create_namespaced_secret(namespace=self._proxy_ns, body=secret)
        except ApiException as e:
            # 409 on create = cold-cluster race lost.
            if e.status in (409, 422):
                raise CAStoreConflictError(
                    f"Secret {self._proxy_ns}/{self._secret_name} already exists"
                ) from e
            raise

        self._ensure_configmap(cert_pem)

    def _ensure_configmap(self, cert_pem: bytes) -> None:
        body = client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=client.V1ObjectMeta(
                name=self._configmap_name,
                namespace=self._sandbox_ns,
                labels={
                    "app.kubernetes.io/managed-by": "onyx",
                    "app.kubernetes.io/component": "sandbox-proxy",
                    "onyx.app/resource": "sandbox-proxy-ca-bundle",
                },
            ),
            data={_CA_CERT_CONFIGMAP_KEY: _decode_cert_for_configmap(cert_pem)},
        )

        try:
            self._core.create_namespaced_config_map(
                namespace=self._sandbox_ns, body=body
            )
            return
        except ApiException as e:
            if e.status != 409:
                raise

        # Replace path — another proxy replica may be updating
        # concurrently. Retry on 409 with exponential backoff. Both
        # replicas hold the same cert, so whichever write lands last
        # converges the ConfigMap to the same value.
        backoff = 0.1
        for attempt in range(_CONFIGMAP_REPLACE_MAX_ATTEMPTS):
            try:
                self._core.replace_namespaced_config_map(
                    name=self._configmap_name,
                    namespace=self._sandbox_ns,
                    body=body,
                )
                return
            except ApiException as e:
                last_attempt = attempt == _CONFIGMAP_REPLACE_MAX_ATTEMPTS - 1
                if e.status == 409 and not last_attempt:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, _CONFIGMAP_REPLACE_MAX_BACKOFF)
                    continue
                raise
