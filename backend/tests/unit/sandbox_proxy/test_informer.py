from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from kubernetes import client

from onyx.sandbox_proxy.identity_k8s import _identity_from_pod
from onyx.sandbox_proxy.identity_k8s import K8sInformerLookup


def _make_pod(
    *,
    name: str = "sandbox-aaaa1111",
    pod_ip: str | None = "10.0.0.1",
    sandbox_id: str | None = "11111111-1111-1111-1111-111111111111",
    tenant_id: str | None = "public",
    managed_by: str | None = "onyx",
) -> client.V1Pod:
    labels: dict[str, str] = {"app.kubernetes.io/component": "sandbox"}
    if managed_by is not None:
        labels["app.kubernetes.io/managed-by"] = managed_by
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


def test_identity_from_pod_rejects_missing_managed_by() -> None:
    assert _identity_from_pod(_make_pod(managed_by=None)) is None


def test_identity_from_pod_rejects_foreign_managed_by() -> None:
    # managed-by is the integrity check: an attacker can forge every other
    # label.
    assert _identity_from_pod(_make_pod(managed_by="someone-else")) is None


def test_initial_list_raises_on_duplicate_ip() -> None:
    other_uuid = "22222222-2222-2222-2222-222222222222"
    listing = client.V1PodList(
        metadata=client.V1ListMeta(resource_version="1"),
        items=[
            _make_pod(name="sandbox-a", pod_ip="10.0.0.1"),
            _make_pod(name="sandbox-b", pod_ip="10.0.0.1", sandbox_id=other_uuid),
        ],
    )
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.list_namespaced_pod.return_value = listing
    lookup = K8sInformerLookup(core_api=core_api)

    with pytest.raises(RuntimeError, match="Duplicate sandbox IP"):
        lookup._initial_list()


def test_synced_clears_after_watch_loop_returns_cleanly() -> None:
    """
    Clean watch EOF clears ``_synced`` so /healthz reports not-ready during the
    reconnect window.
    """
    listing = client.V1PodList(
        metadata=client.V1ListMeta(resource_version="42"),
        items=[],
    )
    core_api = MagicMock(spec=client.CoreV1Api)
    core_api.list_namespaced_pod.return_value = listing
    lookup = K8sInformerLookup(core_api=core_api)

    # Empty iter -> _watch_loop exhausts without raising. Stop after one pass.
    call_count = [0]

    class _StubWatch:
        def stream(self, *_: object, **__: object) -> object:
            call_count[0] += 1
            lookup._stop_event.set()
            return iter([])

        def stop(self) -> None:
            pass

    with patch("onyx.sandbox_proxy.identity_k8s.watch.Watch", _StubWatch):
        lookup._run()

    assert lookup._initial_sync_done.is_set()
    assert not lookup._synced.is_set()
    assert call_count[0] == 1
