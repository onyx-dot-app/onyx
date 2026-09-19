import base64
from unittest.mock import MagicMock

import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.sandbox_proxy.ca import CAStoreConflictError
from onyx.sandbox_proxy.ca_k8s import K8sSecretCAStore


def _api_exception(status: int) -> ApiException:
    e = ApiException(status=status)
    e.status = status
    return e


def _make_store(core_api: MagicMock) -> K8sSecretCAStore:
    return K8sSecretCAStore(
        core_api=core_api,
        proxy_namespace="onyx",
        sandbox_namespace="sandboxes",
        secret_name="sandbox-proxy-ca",
        configmap_name="sandbox-proxy-ca-bundle",
    )


def test_load_returns_none_when_secret_missing() -> None:
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.read_namespaced_secret.side_effect = _api_exception(404)

    store = _make_store(core_api)

    assert store.load() is None


def test_load_decodes_secret_and_projects_configmap() -> None:
    cert_pem = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    key_pem = b"-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n"
    secret = client.V1Secret(
        data={
            "ca.crt": base64.b64encode(cert_pem).decode(),
            "ca.key": base64.b64encode(key_pem).decode(),
        }
    )
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.read_namespaced_secret.return_value = secret
    core_api.create_namespaced_config_map.return_value = None

    store = _make_store(core_api)
    result = store.load()

    assert result == (cert_pem, key_pem)
    # ConfigMap projected even on a warm load (self-heals a deleted CM).
    core_api.create_namespaced_config_map.assert_called_once()


def test_load_raises_on_malformed_secret() -> None:
    secret = client.V1Secret(data={"ca.crt": base64.b64encode(b"x").decode()})
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.read_namespaced_secret.return_value = secret

    store = _make_store(core_api)

    with pytest.raises(RuntimeError, match="is missing"):
        store.load()


def test_load_raises_on_non_base64_data() -> None:
    secret = client.V1Secret(
        data={"ca.crt": "!!!not-base64!!!", "ca.key": "!!!not-base64!!!"}
    )
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.read_namespaced_secret.return_value = secret

    store = _make_store(core_api)

    with pytest.raises(RuntimeError, match="malformed base64"):
        store.load()


def test_persist_create_path_succeeds() -> None:
    cert_pem = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    key_pem = b"-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n"
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.create_namespaced_secret.return_value = None
    core_api.create_namespaced_config_map.return_value = None

    _make_store(core_api).persist(cert_pem, key_pem)

    # Secret carries both keys, base64-encoded, in the proxy namespace.
    secret_call = core_api.create_namespaced_secret.call_args
    assert secret_call.kwargs["namespace"] == "onyx"
    secret_body = secret_call.kwargs["body"]
    assert secret_body.data["ca.crt"] == base64.b64encode(cert_pem).decode()
    assert secret_body.data["ca.key"] == base64.b64encode(key_pem).decode()
    assert secret_body.metadata.labels["app.kubernetes.io/managed-by"] == "onyx"
    assert secret_body.metadata.labels["app.kubernetes.io/component"] == "sandbox-proxy"

    # ConfigMap carries ONLY the cert (no key), in the sandbox namespace.
    cm_call = core_api.create_namespaced_config_map.call_args
    assert cm_call.kwargs["namespace"] == "sandboxes"
    cm_body = cm_call.kwargs["body"]
    assert cm_body.data == {"ca.crt": cert_pem.decode()}
    assert "ca.key" not in cm_body.data


def test_persist_translates_409_to_conflict_error() -> None:
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.create_namespaced_secret.side_effect = _api_exception(409)

    with pytest.raises(CAStoreConflictError):
        _make_store(core_api).persist(b"cert", b"key")

    # Conflict on Secret create must short-circuit — we must NOT touch
    # the ConfigMap with a CA that didn't win the race.
    core_api.create_namespaced_config_map.assert_not_called()


def test_persist_translates_422_to_conflict_error() -> None:
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.create_namespaced_secret.side_effect = _api_exception(422)

    with pytest.raises(CAStoreConflictError):
        _make_store(core_api).persist(b"cert", b"key")

    core_api.create_namespaced_config_map.assert_not_called()


def test_persist_propagates_unexpected_api_exception() -> None:
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.create_namespaced_secret.side_effect = _api_exception(500)

    with pytest.raises(ApiException):
        _make_store(core_api).persist(b"cert", b"key")


def test_ensure_configmap_replaces_on_409(monkeypatch: pytest.MonkeyPatch) -> None:
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.create_namespaced_config_map.side_effect = _api_exception(409)
    core_api.replace_namespaced_config_map.return_value = None
    monkeypatch.setattr("onyx.sandbox_proxy.ca_k8s.time.sleep", lambda _: None)

    _make_store(core_api)._ensure_configmap(
        b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    )

    core_api.replace_namespaced_config_map.assert_called_once()


def test_ensure_configmap_rejects_non_ascii_cert() -> None:
    # A real cert is ASCII PEM; binary garbage should fail loud, not reach the CM.
    core_api = MagicMock(spec=client.CoreV1Api)

    with pytest.raises(RuntimeError, match="not ASCII-encodable PEM"):
        _make_store(core_api)._ensure_configmap(b"\xff\xfe not a PEM")


def test_ensure_configmap_retries_on_repeated_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.create_namespaced_config_map.side_effect = _api_exception(409)
    core_api.replace_namespaced_config_map.side_effect = [
        _api_exception(409),
        _api_exception(409),
        None,
    ]
    monkeypatch.setattr("onyx.sandbox_proxy.ca_k8s.time.sleep", lambda _: None)

    _make_store(core_api)._ensure_configmap(
        b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    )

    assert core_api.replace_namespaced_config_map.call_count == 3
