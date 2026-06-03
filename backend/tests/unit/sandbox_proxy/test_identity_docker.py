import threading
import time
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
    """Returns (lookup, mock_client). Tests configure return_values on the mock.

    Cast the mock to ``DockerClient`` at construction so prod stays properly
    typed; tests interact with the returned mock directly to set up canned
    responses without fighting ty over Container property setters and
    bound-method return types.
    """
    docker_client = MagicMock()
    lookup = DockerEventsLookup(
        docker_client=cast(DockerClient, docker_client),
        network=_DEFAULT_NETWORK,
    )
    return lookup, docker_client


# ------------------------------------------------------------------------------
# _identity_from_container parsing
# ------------------------------------------------------------------------------


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
    # IP exists but only on a different bridge. The proxy's iptables anchor is
    # the sandbox bridge -- IPs on other networks aren't reachable here.
    c = _make_container(ip="10.0.0.1", network="some-other-bridge")
    assert _identity_from_container(c, _DEFAULT_NETWORK) is None


# ------------------------------------------------------------------------------
# DockerEventsLookup._apply_event
# ------------------------------------------------------------------------------


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

    # Container restarted on a new IP -- CNI/bridge reassigns on restart and the
    # stale entry must drop.
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

    # exec_create is a per-command event the events stream emits constantly; it
    # must not touch the cache.
    assert lookup.lookup("172.18.0.5") is not None


def test_apply_event_skips_malformed() -> None:
    lookup, _ = _make_lookup()
    # No Actor; no Action -- defensive against future SDK changes.
    lookup._apply_event({})
    lookup._apply_event({"Action": "start"})
    lookup._apply_event({"Actor": {"ID": "cid-1"}})
    # No exception, no cache mutation.
    assert lookup.lookup("172.18.0.5") is None


def test_apply_event_start_evicts_stale_by_id_on_ip_reclaim() -> None:
    """
    If a start event lands on an IP that ``_cache`` already maps to a different
    container (we missed a die event for the prior owner), the stale ``_by_id``
    entry pointing to that IP must be evicted. Without this, the prior owner's
    eventual die event would pop the new container's cache entry, silently
    un-identifying a live sandbox.
    """
    lookup, client = _make_lookup()
    other_uuid = "22222222-2222-2222-2222-222222222222"

    # Container A starts at IP X.
    client.containers.get.return_value = _make_container(
        container_id="cid-a", ip="172.18.0.5"
    )
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-a"}})
    assert lookup.lookup("172.18.0.5") is not None
    assert lookup._by_id["cid-a"] == "172.18.0.5"

    # Container B starts at the same IP (we missed A's die event).
    client.containers.get.return_value = _make_container(
        container_id="cid-b", sandbox_id=other_uuid, ip="172.18.0.5"
    )
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-b"}})

    # _cache now reflects B; _by_id should NOT still have a stale cid-a entry
    # pointing at this IP (otherwise A's die would wipe B).
    identity = lookup.lookup("172.18.0.5")
    assert identity is not None
    assert str(identity.sandbox_id) == other_uuid
    assert "cid-a" not in lookup._by_id
    assert lookup._by_id["cid-b"] == "172.18.0.5"

    # The original failure mode: A's belated die event must not wipe B.
    lookup._apply_event({"Action": "die", "Actor": {"ID": "cid-a"}})
    identity_after = lookup.lookup("172.18.0.5")
    assert identity_after is not None
    assert str(identity_after.sandbox_id) == other_uuid


def test_apply_event_start_evicts_stale_by_id_on_same_sandbox_id_restart() -> None:
    """
    Sandbox restart keeps the same ``sandbox_id`` label but gets a fresh
    ``container_id`` from docker. The orphan-eviction must not be gated on
    sandbox_id mismatch -- the stale ``_by_id`` entry from the old container_id
    is still poison regardless of whether the new container_id has the same
    sandbox_id. Without this, the prior container's belated die event would wipe
    the restarted container's cache entry.
    """
    lookup, client = _make_lookup()
    # Both containers carry the SAME sandbox_id (default in _make_container).
    # Different container_ids though -- that's the sandbox-restart shape.
    client.containers.get.return_value = _make_container(
        container_id="cid-a", ip="172.18.0.5"
    )
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-a"}})

    # Same sandbox_id, new container_id, same IP (we missed the die for A).
    client.containers.get.return_value = _make_container(
        container_id="cid-b", ip="172.18.0.5"
    )
    lookup._apply_event({"Action": "start", "Actor": {"ID": "cid-b"}})

    assert "cid-a" not in lookup._by_id
    assert lookup._by_id["cid-b"] == "172.18.0.5"

    # A's belated die must not wipe B.
    lookup._apply_event({"Action": "die", "Actor": {"ID": "cid-a"}})
    assert lookup.lookup("172.18.0.5") is not None


# ------------------------------------------------------------------------------
# Initial sync
# ------------------------------------------------------------------------------


def test_initial_sync_raises_on_duplicate_ip() -> None:
    lookup, client = _make_lookup()
    other_uuid = "22222222-2222-2222-2222-222222222222"
    c1 = _make_container(container_id="cid-1", ip="172.18.0.5")
    c2 = _make_container(container_id="cid-2", sandbox_id=other_uuid, ip="172.18.0.5")
    client.containers.list.return_value = [c1, c2]

    with pytest.raises(RuntimeError, match="Duplicate sandbox IP"):
        lookup._initial_sync()


def test_initial_sync_skips_unidentifiable_containers() -> None:
    lookup, client = _make_lookup()
    good = _make_container(container_id="cid-good", ip="172.18.0.5")
    bad = _make_container(container_id="cid-bad", tenant_id=None, ip="172.18.0.6")
    client.containers.list.return_value = [good, bad]

    lookup._initial_sync()

    assert lookup.lookup("172.18.0.5") is not None
    assert lookup.lookup("172.18.0.6") is None


# ------------------------------------------------------------------------------
# Watch loop
# ------------------------------------------------------------------------------


def test_watch_loop_passes_since_to_events() -> None:
    """
    The events stream must start from ``since_ts`` (captured before the list) so
    events fired during the [list, stream-open] window are replayed instead of
    silently dropped. Without ``since`` a sandbox that starts in that gap is
    unidentifiable until the next reconnect.
    """
    lookup, client = _make_lookup()
    # iter([]) so the for-loop in _watch_loop returns immediately.
    client.events.return_value = iter([])

    lookup._watch_loop(since_ts=12345)

    client.events.assert_called_once()
    _, kwargs = client.events.call_args
    assert kwargs["since"] == 12345
    assert kwargs["decode"] is True
    assert kwargs["filters"]["type"] == "container"


def test_stop_closes_active_stream_to_unblock_watch_loop() -> None:
    """
    ``stop()`` must call ``close()`` on the currently-active events stream.
    Without this, the ``for event in stream`` iterator blocks on socket read
    indefinitely in a quiescent system and ``stop()`` is a no-op (the stop_event
    is only checked between events). The daemon thread would never honor stop
    and any future join() would hang.
    """
    lookup, client = _make_lookup()

    # Block the iterator so _watch_loop is mid-for-loop when stop() fires.
    # Concrete class instead of MagicMock-with-lambdas so __next__ can raise
    # StopIteration directly without PEP 479 generator confusion.
    iter_event = threading.Event()
    close_calls = [0]

    class _BlockingStream:
        def __iter__(self) -> "_BlockingStream":
            return self

        def __next__(self) -> dict[str, str]:
            iter_event.wait()
            raise StopIteration

        def close(self) -> None:
            close_calls[0] += 1

    stream_mock = _BlockingStream()
    client.events.return_value = stream_mock

    # Run _watch_loop in a thread so we can call stop() against it.
    thread = threading.Thread(target=lookup._watch_loop, args=(0,))
    thread.start()

    # Wait until _watch_loop has published the stream (i.e. we're past the
    # open-vs-stop race window and into the blocking iterator).
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with lookup._stream_lock:
            if lookup._stream is stream_mock:
                break
        time.sleep(0.01)
    else:
        iter_event.set()
        thread.join(timeout=1.0)
        pytest.fail("_watch_loop never published its stream.")

    lookup.stop()
    # stop() must have invoked close() on the live stream.
    assert close_calls[0] >= 1

    # Release the blocking iterator so the thread can drain its finally block.
    # In production, close() would raise OSError -> StopIteration inside the
    # iterator; here we just unblock it directly.
    iter_event.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive(), "_watch_loop thread failed to exit after stop()."


def test_synced_clears_after_watch_loop_returns_cleanly() -> None:
    """
    Clean watch EOF clears ``_synced`` so /healthz reports not-ready during the
    reconnect window.
    """
    lookup, client = _make_lookup()
    client.containers.list.return_value = []

    # Empty iter -> _watch_loop exhausts without raising. Stop after one pass.
    call_count = [0]

    def events_side_effect(**_: object) -> object:
        call_count[0] += 1
        lookup._stop_event.set()
        return iter([])

    client.events.side_effect = events_side_effect

    lookup._run()

    assert lookup._initial_sync_done.is_set()
    assert not lookup._synced.is_set()
    assert call_count[0] == 1


def test_watch_loop_close_race_when_stop_fires_between_open_and_publish() -> None:
    """
    If ``stop()`` runs between ``events()`` returning and the stream being
    published under the lock, ``_watch_loop`` must close the just-opened stream
    itself rather than entering the blocking iterator. Otherwise the stop_event
    is set but no one holds a reference to the stream to cancel it.
    """
    lookup, client = _make_lookup()
    stream_mock = MagicMock()
    client.events.return_value = stream_mock

    # Pre-set the stop event so _watch_loop sees it under the lock and bails
    # before assigning self._stream.
    lookup._stop_event.set()

    lookup._watch_loop(since_ts=0)

    stream_mock.close.assert_called_once()
    assert lookup._stream is None
