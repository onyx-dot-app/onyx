from unittest.mock import MagicMock

from kubernetes import client

from onyx.sandbox_proxy.identity_k8s import _identity_from_pod
from onyx.sandbox_proxy.identity_k8s import K8sInformerLookup


def _make_pod(
    *,
    name: str = "sandbox-aaaa1111",
    pod_ip: str | None = "10.0.0.1",
    sandbox_id: str | None = "11111111-1111-1111-1111-111111111111",
    tenant_id: str | None = "public",
) -> client.V1Pod:
    labels: dict[str, str] = {"app.kubernetes.io/component": "sandbox"}
    if sandbox_id is not None:
        labels["onyx.app/sandbox-id"] = sandbox_id
    if tenant_id is not None:
        labels["onyx.app/tenant-id"] = tenant_id
    return client.V1Pod(
        metadata=client.V1ObjectMeta(name=name, labels=labels),
        status=client.V1PodStatus(pod_ip=pod_ip),
    )


def _make_lookup() -> K8sInformerLookup:
    return K8sInformerLookup(core_api=MagicMock(spec=client.CoreV1Api))


def test_identity_from_pod_returns_none_when_missing_ip() -> None:
    assert _identity_from_pod(_make_pod(pod_ip=None)) is None


def test_identity_from_pod_returns_none_when_missing_sandbox_id() -> None:
    assert _identity_from_pod(_make_pod(sandbox_id=None)) is None


def test_identity_from_pod_returns_none_when_missing_tenant_id() -> None:
    assert _identity_from_pod(_make_pod(tenant_id=None)) is None


def test_identity_from_pod_skips_non_uuid_sandbox_id() -> None:
    assert _identity_from_pod(_make_pod(sandbox_id="not-a-uuid")) is None


def test_identity_from_pod_happy_path() -> None:
    identity = _identity_from_pod(_make_pod())
    assert identity is not None
    assert str(identity.sandbox_id) == "11111111-1111-1111-1111-111111111111"
    assert identity.tenant_id == "public"
    assert identity.sandbox_ip == "10.0.0.1"
    assert identity.sandbox_name == "sandbox-aaaa1111"


def test_apply_event_added_populates_cache() -> None:
    lookup = _make_lookup()
    lookup._apply_event({"type": "ADDED", "object": _make_pod()})

    identity = lookup.lookup("10.0.0.1")
    assert identity is not None
    assert identity.sandbox_name == "sandbox-aaaa1111"


def test_apply_event_modified_with_new_ip_evicts_old() -> None:
    lookup = _make_lookup()
    lookup._apply_event({"type": "ADDED", "object": _make_pod(pod_ip="10.0.0.1")})
    assert lookup.lookup("10.0.0.1") is not None

    lookup._apply_event({"type": "MODIFIED", "object": _make_pod(pod_ip="10.0.0.2")})

    assert lookup.lookup("10.0.0.1") is None
    new_identity = lookup.lookup("10.0.0.2")
    assert new_identity is not None
    assert new_identity.sandbox_ip == "10.0.0.2"


def test_apply_event_deleted_evicts_cache() -> None:
    lookup = _make_lookup()
    pod = _make_pod()
    lookup._apply_event({"type": "ADDED", "object": pod})
    lookup._apply_event({"type": "DELETED", "object": pod})

    assert lookup.lookup("10.0.0.1") is None


def test_apply_event_modified_without_ip_evicts_pending_pod() -> None:
    lookup = _make_lookup()
    lookup._apply_event({"type": "ADDED", "object": _make_pod(pod_ip="10.0.0.1")})

    lookup._apply_event({"type": "MODIFIED", "object": _make_pod(pod_ip=None)})

    assert lookup.lookup("10.0.0.1") is None


def test_lookup_returns_none_for_unknown_ip() -> None:
    lookup = _make_lookup()
    assert lookup.lookup("203.0.113.99") is None
