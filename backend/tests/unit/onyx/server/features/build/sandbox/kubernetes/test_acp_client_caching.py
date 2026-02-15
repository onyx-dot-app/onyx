"""Unit tests for ACPExecClient caching behavior in KubernetesSandboxManager.

These tests verify that the KubernetesSandboxManager correctly caches
ACPExecClient instances per (sandbox_id, session_id) pair, reuses them
across send_message calls, replaces dead clients, and cleans them up
on terminate/cleanup.

All external dependencies (K8s, WebSockets, packet logging) are mocked.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The fully-qualified path to the module under test, used for patching
_K8S_MODULE = "onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager"
_ACP_CLIENT_CLASS = f"{_K8S_MODULE}.ACPExecClient"
_GET_PACKET_LOGGER = f"{_K8S_MODULE}.get_packet_logger"


def _make_mock_event() -> MagicMock:
    """Create a mock ACP event."""
    return MagicMock(name="mock_acp_event")


def _make_mock_client(is_running: bool = True) -> MagicMock:
    """Create a mock ACPExecClient with configurable is_running property."""
    mock_client = MagicMock()
    type(mock_client).is_running = property(lambda _self: is_running)
    mock_client.start.return_value = "mock-session-id"
    mock_event = _make_mock_event()
    mock_client.send_message.return_value = iter([mock_event])
    mock_client.stop.return_value = None
    return mock_client


def _drain_generator(gen: Generator[Any, None, None]) -> list[Any]:
    """Consume a generator and return all yielded values as a list."""
    return list(gen)


# ---------------------------------------------------------------------------
# Fixture: fresh KubernetesSandboxManager instance
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> Generator[Any, None, None]:
    """Create a fresh KubernetesSandboxManager instance with all externals mocked.

    This fixture:
    1. Resets the singleton _instance so each test gets a fresh manager
    2. Mocks kubernetes.config and kubernetes.client to prevent real K8s calls
    3. Mocks get_packet_logger to prevent logging side effects
    """
    # Import here so patches are in effect when the class loads
    with (
        patch(f"{_K8S_MODULE}.config") as _mock_config,
        patch(f"{_K8S_MODULE}.client") as _mock_k8s_client,
        patch(f"{_K8S_MODULE}.k8s_stream"),
        patch(_GET_PACKET_LOGGER) as mock_get_logger,
    ):
        # Set up the mock packet logger
        mock_packet_logger = MagicMock()
        mock_get_logger.return_value = mock_packet_logger

        # Make config.load_incluster_config succeed (no-op)
        _mock_config.load_incluster_config.return_value = None
        _mock_config.ConfigException = Exception

        # Make client constructors return mocks
        _mock_k8s_client.ApiClient.return_value = MagicMock()
        _mock_k8s_client.CoreV1Api.return_value = MagicMock()
        _mock_k8s_client.BatchV1Api.return_value = MagicMock()
        _mock_k8s_client.NetworkingV1Api.return_value = MagicMock()

        # Reset singleton before importing
        from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
            KubernetesSandboxManager,
        )

        KubernetesSandboxManager._instance = None

        mgr = KubernetesSandboxManager()

        # Ensure the _acp_clients dict exists (it should be initialized by
        # the caching implementation)
        if not hasattr(mgr, "_acp_clients"):
            mgr._acp_clients = {}

        yield mgr

        # Reset singleton after test
        KubernetesSandboxManager._instance = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_send_message_creates_client_on_first_call(manager: Any) -> None:
    """First call to send_message() should create a new ACPExecClient,
    call start(), cache it, and yield events from send_message()."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()
    message = "hello world"

    mock_event = _make_mock_event()
    mock_client = _make_mock_client(is_running=True)
    mock_client.send_message.return_value = iter([mock_event])

    with patch(_ACP_CLIENT_CLASS, return_value=mock_client) as MockClass:
        events = _drain_generator(manager.send_message(sandbox_id, session_id, message))

    # Verify client was constructed
    MockClass.assert_called_once()

    # Verify start() was called with the correct session path
    expected_cwd = f"/workspace/sessions/{session_id}"
    mock_client.start.assert_called_once_with(cwd=expected_cwd)

    # Verify send_message was called on the client
    mock_client.send_message.assert_called_once_with(message)

    # Verify we got the event
    assert len(events) >= 1
    # Find our mock event (filter out any SSEKeepalive or similar)
    assert mock_event in events

    # Verify client was cached
    client_key = (sandbox_id, session_id)
    assert client_key in manager._acp_clients
    assert manager._acp_clients[client_key] is mock_client


def test_send_message_reuses_cached_client(manager: Any) -> None:
    """Second call with the same (sandbox_id, session_id) should NOT create
    a new client. Should reuse the cached one."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()
    message_1 = "first message"
    message_2 = "second message"

    mock_event_1 = _make_mock_event()
    mock_event_2 = _make_mock_event()
    mock_client = _make_mock_client(is_running=True)

    # send_message returns different events for each call
    mock_client.send_message.side_effect = [
        iter([mock_event_1]),
        iter([mock_event_2]),
    ]

    with patch(_ACP_CLIENT_CLASS, return_value=mock_client) as MockClass:
        events_1 = _drain_generator(
            manager.send_message(sandbox_id, session_id, message_1)
        )
        events_2 = _drain_generator(
            manager.send_message(sandbox_id, session_id, message_2)
        )

    # Constructor called only ONCE (on first send_message)
    MockClass.assert_called_once()

    # start() called only once
    mock_client.start.assert_called_once()

    # send_message called twice with different messages
    assert mock_client.send_message.call_count == 2
    mock_client.send_message.assert_any_call(message_1)
    mock_client.send_message.assert_any_call(message_2)

    # Both calls yielded events
    assert mock_event_1 in events_1
    assert mock_event_2 in events_2


def test_send_message_replaces_dead_client(manager: Any) -> None:
    """If cached client has is_running == False, should create a new one,
    start it, and cache the replacement."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()
    message = "test message"

    # Create a dead client (is_running = False) and place it in the cache
    dead_client = _make_mock_client(is_running=False)
    client_key = (sandbox_id, session_id)
    manager._acp_clients[client_key] = dead_client

    # Create the replacement client
    new_event = _make_mock_event()
    new_client = _make_mock_client(is_running=True)
    new_client.send_message.return_value = iter([new_event])

    with patch(_ACP_CLIENT_CLASS, return_value=new_client) as MockClass:
        events = _drain_generator(manager.send_message(sandbox_id, session_id, message))

    # A new client was constructed (the dead one was replaced)
    MockClass.assert_called_once()

    # New client was started and used
    new_client.start.assert_called_once()
    new_client.send_message.assert_called_once_with(message)

    # Cache now holds the new client
    assert manager._acp_clients[client_key] is new_client

    # Events from new client were yielded
    assert new_event in events


def test_send_message_different_sessions_get_different_clients(
    manager: Any,
) -> None:
    """Two calls with different session_id values should create two
    separate clients, each cached under its own key."""
    sandbox_id: UUID = uuid4()
    session_id_a: UUID = uuid4()
    session_id_b: UUID = uuid4()
    message = "test"

    mock_client_a = _make_mock_client(is_running=True)
    mock_client_b = _make_mock_client(is_running=True)

    mock_event_a = _make_mock_event()
    mock_event_b = _make_mock_event()
    mock_client_a.send_message.return_value = iter([mock_event_a])
    mock_client_b.send_message.return_value = iter([mock_event_b])

    with patch(
        _ACP_CLIENT_CLASS, side_effect=[mock_client_a, mock_client_b]
    ) as MockClass:
        events_a = _drain_generator(
            manager.send_message(sandbox_id, session_id_a, message)
        )
        events_b = _drain_generator(
            manager.send_message(sandbox_id, session_id_b, message)
        )

    # Two separate clients were constructed
    assert MockClass.call_count == 2

    # Both were started
    mock_client_a.start.assert_called_once()
    mock_client_b.start.assert_called_once()

    # Each is cached under a different key
    assert manager._acp_clients[(sandbox_id, session_id_a)] is mock_client_a
    assert manager._acp_clients[(sandbox_id, session_id_b)] is mock_client_b

    # Events from each client are correct
    assert mock_event_a in events_a
    assert mock_event_b in events_b


def test_terminate_stops_all_sandbox_clients(manager: Any) -> None:
    """terminate(sandbox_id) should stop all cached clients for that
    sandbox and remove them from the cache."""
    sandbox_id: UUID = uuid4()
    session_id_1: UUID = uuid4()
    session_id_2: UUID = uuid4()

    client_1 = _make_mock_client(is_running=True)
    client_2 = _make_mock_client(is_running=True)

    manager._acp_clients[(sandbox_id, session_id_1)] = client_1
    manager._acp_clients[(sandbox_id, session_id_2)] = client_2

    # Mock _cleanup_kubernetes_resources to prevent actual K8s calls
    with patch.object(manager, "_cleanup_kubernetes_resources"):
        manager.terminate(sandbox_id)

    # Both clients should have been stopped
    client_1.stop.assert_called_once()
    client_2.stop.assert_called_once()

    # Both should be removed from cache
    assert (sandbox_id, session_id_1) not in manager._acp_clients
    assert (sandbox_id, session_id_2) not in manager._acp_clients


def test_terminate_leaves_other_sandbox_clients(manager: Any) -> None:
    """terminate(sandbox_id_A) should NOT affect clients cached for
    sandbox_id_B."""
    sandbox_id_a: UUID = uuid4()
    sandbox_id_b: UUID = uuid4()
    session_id_a: UUID = uuid4()
    session_id_b: UUID = uuid4()

    client_a = _make_mock_client(is_running=True)
    client_b = _make_mock_client(is_running=True)

    manager._acp_clients[(sandbox_id_a, session_id_a)] = client_a
    manager._acp_clients[(sandbox_id_b, session_id_b)] = client_b

    # Terminate only sandbox A
    with patch.object(manager, "_cleanup_kubernetes_resources"):
        manager.terminate(sandbox_id_a)

    # Client A stopped and removed
    client_a.stop.assert_called_once()
    assert (sandbox_id_a, session_id_a) not in manager._acp_clients

    # Client B untouched
    client_b.stop.assert_not_called()
    assert (sandbox_id_b, session_id_b) in manager._acp_clients
    assert manager._acp_clients[(sandbox_id_b, session_id_b)] is client_b


def test_cleanup_session_stops_session_client(manager: Any) -> None:
    """cleanup_session_workspace(sandbox_id, session_id) should stop and
    remove the specific session's client from the cache."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()

    cached_client = _make_mock_client(is_running=True)
    manager._acp_clients[(sandbox_id, session_id)] = cached_client

    # Mock the k8s exec call that runs the cleanup script
    with patch.object(manager, "_stream_core_api") as mock_stream_api:
        mock_stream_api.connect_get_namespaced_pod_exec = MagicMock()
        with patch(f"{_K8S_MODULE}.k8s_stream", return_value="cleanup ok"):
            manager.cleanup_session_workspace(sandbox_id, session_id)

    # Client should have been stopped
    cached_client.stop.assert_called_once()

    # Client should be removed from the cache
    assert (sandbox_id, session_id) not in manager._acp_clients


def test_cleanup_session_handles_no_cached_client(manager: Any) -> None:
    """cleanup_session_workspace() should not error when there's no cached
    client for that session."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()

    # Ensure no client is cached for this pair
    assert (sandbox_id, session_id) not in manager._acp_clients

    # Mock the k8s exec call that runs the cleanup script
    with patch.object(manager, "_stream_core_api") as mock_stream_api:
        mock_stream_api.connect_get_namespaced_pod_exec = MagicMock()
        with patch(f"{_K8S_MODULE}.k8s_stream", return_value="cleanup ok"):
            # This should NOT raise
            manager.cleanup_session_workspace(sandbox_id, session_id)

    # Cache is still empty for this key
    assert (sandbox_id, session_id) not in manager._acp_clients
