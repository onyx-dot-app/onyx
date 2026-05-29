from typing import cast
from unittest.mock import MagicMock

import pytest
from docker import DockerClient

from onyx.sandbox_proxy.identity_docker import _identity_from_container
from onyx.sandbox_proxy.identity_docker import DockerEventsLookup

_DEFAULT_NETWORK = "onyx_craft_sandbox"


def _make_container(
    *,
    name: str = "sandbox-aaaa1111",
    container_id: str = "container-id-1",
    sandbox_id: str | None = "11111111-1111-1111-1111-111111111111",
    tenant_id: str | None = "public",
    component: str | None = "craft-sandbox",
    ip: str | None = "172.18.0.5",
    network: str = _DEFAULT_NETWORK,
) -> MagicMock:
    """Mock that quacks like ``docker.models.containers.Container``.

    No ``spec=Container`` because the SDK declares ``labels`` as a read-only
    property; we need to assign to it to seed the test fixture.
    """
    labels: dict[str, str] = {}
    if component is not None:
        labels["onyx.app/component"] = component
    if sandbox_id is not None:
        labels["onyx.app/sandbox-id"] = sandbox_id
    if tenant_id is not None:
        labels["onyx.app/tenant-id"] = tenant_id

    networks: dict[str, dict[str, str]] = {}
    if ip is not None:
        networks[network] = {"IPAddress": ip}

    container = MagicMock()
    container.name = name
    container.id = container_id
    container.labels = labels
    container.attrs = {"NetworkSettings": {"Networks": networks}}
    return container


def _make_lookup() -> tuple[DockerEventsLookup, MagicMock]:
    """Return (lookup, mock_client). Tests configure return_values on the mock.

    Cast the mock to ``DockerClient`` at construction so prod stays
    properly typed; tests interact with the returned mock directly to
    set up canned responses without fighting ty over Container property
    setters and bound-method return types.
    """
    docker_client = MagicMock()
    lookup = DockerEventsLookup(
        docker_client=cast(DockerClient, docker_client),
        network=_DEFAULT_NETWORK,
    )
    return lookup, docker_client


# ---------------------------------------------------------------------------
# _identity_from_container parsing
# ---------------------------------------------------------------------------


def test_identity_from_container_happy_path() -> None:
    identity = _identity_from_container(_make_container(), _DEFAULT_NETWORK)
    assert identity is not None
    assert str(identity.sandbox_id) == "11111111-1111-1111-1111-111111111111"
    assert identity.tenant_id == "public"
    assert identity.sandbox_ip == "172.18.0.5"
    assert identity.sandbox_name == "sandbox-aaaa1111"


def test_identity_from_container_rejects_wrong_component_label() -> None:
    # Belt-and-braces against a future filter loosen that lets a non-sandbox
    # labelled container through. Identity must come from the right kind of
    # container or the gate's downstream logic is operating on junk.
    assert (
        _identity_from_container(
            _make_container(component="sandbox-proxy"), _DEFAULT_NETWORK
        )
        is None
    )


def test_identity_from_container_rejects_missing_sandbox_id() -> None:
    assert (
        _identity_from_container(_make_container(sandbox_id=None), _DEFAULT_NETWORK)
        is None
    )


def test_identity_from_container_rejects_missing_tenant_id() -> None:
    assert (
        _identity_from_container(_make_container(tenant_id=None), _DEFAULT_NETWORK)
        is None
    )


def test_identity_from_container_rejects_non_uuid_sandbox_id() -> None:
    assert (
        _identity_from_container(
            _make_container(sandbox_id="not-a-uuid"), _DEFAULT_NETWORK
        )
        is None
    )


def test_identity_from_container_returns_none_when_no_ip_on_network() -> None:
    # Container created but not yet attached to the network -- legitimate
    # transient state mid-provision; cache should just skip it.
    assert _identity_from_container(_make_container(ip=None), _DEFAULT_NETWORK) is None


def test_identity_from_container_returns_none_when_ip_on_wrong_network() -> None:
    # IP exists but only on a different bridge. The proxy's iptables anchor
    # is the sandbox bridge -- IPs on other networks aren't reachable here.
    c = _make_container(ip="10.0.0.1", network="some-other-bridge")
    assert _identity_from_container(c, _DEFAULT_NETWORK) is None


# ---------------------------------------------------------------------------
# DockerEventsLookup._apply_event
# ---------------------------------------------------------------------------


def test_apply_event_start_populates_cache() -> None:
    lookup, client = _make_lookup()
    client.containers.get.return_value = _make_container(
        container_id="cid-1", ip="172.18.0.5"
    )

    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-1"}})

    identity = lookup.lookup("172.18.0.5")
    assert identity is not None
    assert identity.sandbox_name == "sandbox-aaaa1111"


def test_apply_event_start_with_new_ip_evicts_stale() -> None:
    lookup, client = _make_lookup()
    client.containers.get.return_value = _make_container(
        container_id="cid-1", ip="172.18.0.5"
    )
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-1"}})
    assert lookup.lookup("172.18.0.5") is not None

    # Container restarted on a new IP -- CNI/bridge reassigns on restart and
    # the stale entry must drop.
    client.containers.get.return_value = _make_container(
        container_id="cid-1", ip="172.18.0.6"
    )
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-1"}})

    assert lookup.lookup("172.18.0.5") is None
    assert lookup.lookup("172.18.0.6") is not None


def test_apply_event_die_evicts_cache() -> None:
    lookup, client = _make_lookup()
    client.containers.get.return_value = _make_container(container_id="cid-1")
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-1"}})

    lookup._apply_event({"Action": "die", "Actor": {"ID": "cid-1"}})

    assert lookup.lookup("172.18.0.5") is None


def test_apply_event_destroy_evicts_cache() -> None:
    lookup, client = _make_lookup()
    client.containers.get.return_value = _make_container(container_id="cid-1")
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-1"}})

    lookup._apply_event({"Action": "destroy", "Actor": {"ID": "cid-1"}})

    assert lookup.lookup("172.18.0.5") is None


def test_apply_event_ignores_unknown_actions() -> None:
    lookup, client = _make_lookup()
    client.containers.get.return_value = _make_container(container_id="cid-1")
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-1"}})

    lookup._apply_event({"Action": "exec_create", "Actor": {"ID": "cid-1"}})

    # exec_create is a per-command event the events stream emits constantly;
    # it must not touch the cache.
    assert lookup.lookup("172.18.0.5") is not None


def test_apply_event_skips_malformed() -> None:
    lookup, _ = _make_lookup()
    # No Actor; no Action -- defensive against future SDK changes.
    lookup._apply_event({})
    lookup._apply_event({"Action": "start"})
    lookup._apply_event({"Actor": {"ID": "cid-1"}})
    # No exception, no cache mutation.
    assert lookup.lookup("172.18.0.5") is None


def test_synced_clears_after_watch_loop_returns_cleanly() -> None:
    """A clean return from ``_watch_loop`` (stream EOF, daemon close,
    network hiccup -- all converted to StopIteration by
    CancellableStream) must clear ``_synced``. Otherwise ``/healthz``
    keeps reporting 200 during the reconnect backoff window even
    though we are not actively watching events; a sandbox starting in
    that window would 403 with ``gate.unidentified_sandbox`` because
    the cache never saw its start event.
    """
    lookup, client = _make_lookup()
    client.containers.list.return_value = []

    # events() returns an empty iterator so _watch_loop's for-loop
    # exhausts immediately, simulating a clean daemon-side close. Set
    # stop after the first iteration so _run exits.
    call_count = [0]

    def events_side_effect(**_: object) -> object:
        call_count[0] += 1
        if call_count[0] >= 1:
            lookup._stop_event.set()
        return iter([])

    client.events.side_effect = events_side_effect

    lookup._run()

    # The full iteration ran: _initial_sync_done was set, _synced was
    # set inside the try, and the finally clause cleared _synced again.
    assert lookup._initial_sync_done.is_set()
    assert not lookup._synced.is_set()
    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Initial sync
# ---------------------------------------------------------------------------


def test_initial_sync_raises_on_duplicate_ip() -> None:
    lookup, client = _make_lookup()
    other_uuid = "22222222-2222-2222-2222-222222222222"
    c1 = _make_container(container_id="cid-1", ip="172.18.0.5")
    c2 = _make_container(container_id="cid-2", sandbox_id=other_uuid, ip="172.18.0.5")
    client.containers.list.return_value = [c1, c2]

    with pytest.raises(RuntimeError, match="duplicate sandbox IP"):
        lookup._initial_sync()


def test_initial_sync_skips_unidentifiable_containers() -> None:
    lookup, client = _make_lookup()
    good = _make_container(container_id="cid-good", ip="172.18.0.5")
    bad = _make_container(container_id="cid-bad", tenant_id=None, ip="172.18.0.6")
    client.containers.list.return_value = [good, bad]

    lookup._initial_sync()

    assert lookup.lookup("172.18.0.5") is not None
    assert lookup.lookup("172.18.0.6") is None
