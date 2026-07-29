"""Tests for per-(sandbox_id, directory) :class:`PodEventBus` keying in
:class:`KubernetesSandboxManager`.

Production bug (May 2026): when two build sessions ran on the same
opencode-serve pod, both sessions shared one bus subscribed to
``GET /event`` with no ``?directory=`` query param. opencode-serve's
``Instance.provide`` middleware scopes /event per directory, so the
shared bus only saw the default Instance's global events
(``server.connected``, ``server.heartbeat``) — *no* session events for
either session. Both sessions hung waiting for terminators that would
never arrive.

The fix:

1. ``PodEventBus`` accepts ``directory=...`` and passes it as
   ``?directory=`` to /event (wire-level scoping; tested in
   ``test_event_bus.py``).
2. ``KubernetesSandboxManager._event_buses`` is keyed by
   ``(sandbox_id, directory)`` — one bus per session directory on the
   pod. Parallel sessions get *distinct* buses, each subscribed to its
   own ``?directory=``, so events stay scoped end to end.
3. ``terminate(sandbox_id)`` closes **all** per-directory buses for the
   sandbox in one shot — otherwise tearing down a pod would leak any
   bus that wasn't keyed by the sandbox's most-recent directory.
4. ``list_subagents`` walks every per-directory bus for the sandbox
   (the parent session lives in exactly one of them).

These tests pin those invariants directly against the manager so a
future refactor that flattens the key back to ``sandbox_id`` (or scopes
``terminate`` to one directory) fails loudly.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import nullcontext
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mgr(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[KubernetesSandboxManager, None, None]:
    """Manager with just serve-transport state initialized; stubs the
    connection-info loader and database status lookup so the test doesn't
    touch external services."""
    from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo

    monkeypatch.setattr(
        serve_transport,
        "get_session_with_current_tenant",
        lambda: nullcontext(MagicMock()),
    )
    monkeypatch.setattr(serve_transport, "get_sandbox_by_id", lambda *_: None)

    m: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    m._init_serve_state()

    m._load_serve_connection_info = (  # type: ignore[assignment]
        lambda sandbox_id: ServeConnectionInfo(
            base_url=f"http://{sandbox_id}.invalid:4096",
            password=None,
        )
    )

    try:
        yield m
    finally:
        # Close any buses the test created so reader threads don't linger.
        with m._event_buses_lock:
            buses = list(m._event_buses.values())
            m._event_buses.clear()
        for bus in buses:
            bus.close()


# Two distinct session directories on the same pod — the production
# scenario the bug reproduced under.
_DIR_A = "/workspace/sessions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_DIR_B = "/workspace/sessions/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# Per-(sandbox_id, directory) keying
# ---------------------------------------------------------------------------


def test_two_directories_on_same_pod_get_distinct_buses(
    mgr: KubernetesSandboxManager,
) -> None:
    """The core fix: two sessions on the same pod (same sandbox_id, but
    different session directories) MUST get separate ``PodEventBus``
    instances — one per ``?directory=``. If they shared a bus, the bus
    would be subscribed to a single Instance's event stream and the
    other session's events would never arrive."""
    sandbox_id = uuid4()
    bus_a = mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    bus_b = mgr._get_or_create_event_bus(sandbox_id, _DIR_B)
    assert bus_a is not bus_b
    # Each bus carries its own ``?directory=`` for the GET /event call.
    assert bus_a._directory == _DIR_A
    assert bus_b._directory == _DIR_B


def test_same_directory_returns_cached_bus(mgr: KubernetesSandboxManager) -> None:
    """Memoization: repeat calls for the same ``(sandbox_id, directory)``
    return the same bus instance — otherwise every send_message would
    spin up a fresh reader thread + httpx client."""
    sandbox_id = uuid4()
    bus_1 = mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    bus_2 = mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    assert bus_1 is bus_2


def test_different_sandboxes_same_directory_get_distinct_buses(
    mgr: KubernetesSandboxManager,
) -> None:
    """Same directory string on two different pods is still two buses —
    the sandbox_id half of the key keeps cross-pod isolation."""
    sandbox_1, sandbox_2 = uuid4(), uuid4()
    bus_1 = mgr._get_or_create_event_bus(sandbox_1, _DIR_A)
    bus_2 = mgr._get_or_create_event_bus(sandbox_2, _DIR_A)
    assert bus_1 is not bus_2


# ---------------------------------------------------------------------------
# terminate() must close ALL per-directory buses for the sandbox
# ---------------------------------------------------------------------------


def test_terminate_closes_every_per_directory_bus_for_sandbox(
    mgr: KubernetesSandboxManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug's mirror image: with the new keying, ``terminate`` must
    iterate every key whose first element is ``sandbox_id`` and close
    each bus. If somebody regresses ``terminate`` to ``_event_buses.pop(
    sandbox_id, None)`` (the old single-key form), the other directory's
    bus would leak — its reader thread + httpx client would survive the
    pod deletion and eventually exhaust the reconnect budget against a
    dead pod."""
    sandbox_id = uuid4()
    # Two buses on the same pod, plus one on an unrelated pod that must
    # NOT be touched.
    bus_a = mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    bus_b = mgr._get_or_create_event_bus(sandbox_id, _DIR_B)
    other_sandbox = uuid4()
    bus_other = mgr._get_or_create_event_bus(other_sandbox, _DIR_A)

    # Stub out the K8s teardown — we only care about the bus-close path.
    monkeypatch.setattr(mgr, "_cleanup_kubernetes_resources", lambda _sandbox_str: None)

    mgr.terminate(sandbox_id)

    # Both of the terminated sandbox's buses are closed and removed.
    assert bus_a.closed
    assert bus_b.closed
    with mgr._event_buses_lock:
        keys = list(mgr._event_buses.keys())
    assert (sandbox_id, _DIR_A) not in keys
    assert (sandbox_id, _DIR_B) not in keys

    # The unrelated sandbox's bus survives.
    assert not bus_other.closed
    assert (other_sandbox, _DIR_A) in keys

    # And the tombstone is set so a late ``_get_or_create_event_bus``
    # against the terminated sandbox can't race in and rebuild a bus.
    with pytest.raises(RuntimeError, match="terminated"):
        mgr._get_or_create_event_bus(sandbox_id, _DIR_A)


# ---------------------------------------------------------------------------
# list_subagents must walk every per-directory bus for the sandbox
# ---------------------------------------------------------------------------


def test_list_subagents_finds_parent_in_any_per_directory_bus(
    mgr: KubernetesSandboxManager,
) -> None:
    """Subagent parent-child mappings live on whichever bus the
    ``session.created`` event happened to land on (i.e. the bus for the
    parent's directory). With per-directory keying, ``list_subagents``
    must walk every bus belonging to the sandbox; a regression that
    only checks one bus would intermittently return ``[]`` for parents
    whose directory wasn't the first key inserted."""
    sandbox_id = uuid4()
    # Two buses, but the parent session.created event arrives only on
    # bus B — list_subagents must still find it.
    mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    bus_b = mgr._get_or_create_event_bus(sandbox_id, _DIR_B)

    bus_b._dispatch(
        {
            "type": "session.created",
            "properties": {
                "sessionID": "ses_child",
                "info": {"id": "ses_child", "parentID": "ses_parent"},
            },
        }
    )

    assert mgr.list_subagents(sandbox_id, "ses_parent") == ["ses_child"]


def test_list_subagents_returns_empty_when_no_bus_holds_the_parent(
    mgr: KubernetesSandboxManager,
) -> None:
    """Sanity: with buses present but no session.created seen, the
    method must return ``[]`` — not raise, not return some other
    session's children."""
    sandbox_id = uuid4()
    mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    mgr._get_or_create_event_bus(sandbox_id, _DIR_B)
    assert mgr.list_subagents(sandbox_id, "ses_unknown_parent") == []


def test_list_subagents_does_not_create_a_bus_just_to_check(
    mgr: KubernetesSandboxManager,
) -> None:
    """``list_subagents`` is called on hot paths (UI polling); it must
    not spin up a bus + reader thread for a sandbox that has none.
    Empty pod → empty list, zero side effects."""
    sandbox_id = uuid4()
    assert mgr.list_subagents(sandbox_id, "ses_anything") == []
    with mgr._event_buses_lock:
        assert mgr._event_buses == {}


# ---------------------------------------------------------------------------
# Self-closed bus replacement still works under per-directory keying
# ---------------------------------------------------------------------------


def test_self_closed_bus_is_replaced_for_same_directory(
    mgr: KubernetesSandboxManager,
) -> None:
    """The existing self-close replacement path (see
    ``test_bus_closed_property.py``) must still work after the keying
    change — otherwise a pod that survives a transient outage would
    stay wedged on its dead bus forever."""
    sandbox_id = uuid4()
    bus_1 = mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    bus_1.close()  # simulate self-close from exhausted reconnect budget
    assert bus_1.closed

    bus_2 = mgr._get_or_create_event_bus(sandbox_id, _DIR_A)
    assert bus_2 is not bus_1
    assert not bus_2.closed
