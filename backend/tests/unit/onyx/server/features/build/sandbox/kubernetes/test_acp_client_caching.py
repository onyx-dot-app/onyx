"""Unit tests for Zed-style ACP session management in KubernetesSandboxManager.

These tests verify that the KubernetesSandboxManager correctly:
- Maintains one shared ACPExecClient per sandbox
- Maps craft sessions to ACP sessions on the shared client
- Replaces dead clients and re-creates sessions
- Cleans up on terminate/cleanup

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


def _make_mock_client(
    is_running: bool = True,
    session_ids: list[str] | None = None,
) -> MagicMock:
    """Create a mock ACPExecClient with configurable state.

    Args:
        is_running: Whether the client appears running
        session_ids: List of ACP session IDs the client tracks
    """
    mock_client = MagicMock()
    type(mock_client).is_running = property(lambda _self: is_running)
    type(mock_client).session_ids = property(
        lambda _self: session_ids if session_ids is not None else []
    )
    mock_client.start.return_value = None
    mock_client.stop.return_value = None

    # get_or_create_session returns a unique ACP session ID
    mock_client.get_or_create_session.return_value = f"acp-session-{uuid4().hex[:8]}"

    mock_event = _make_mock_event()
    mock_client.send_message.return_value = iter([mock_event])
    return mock_client


def _drain_generator(gen: Generator[Any, None, None]) -> list[Any]:
    """Consume a generator and return all yielded values as a list."""
    return list(gen)


# ---------------------------------------------------------------------------
# Fixture: fresh KubernetesSandboxManager instance
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> Generator[Any, None, None]:
    """Create a fresh KubernetesSandboxManager instance with all externals mocked."""
    with (
        patch(f"{_K8S_MODULE}.config") as _mock_config,
        patch(f"{_K8S_MODULE}.client") as _mock_k8s_client,
        patch(f"{_K8S_MODULE}.k8s_stream"),
        patch(_GET_PACKET_LOGGER) as mock_get_logger,
    ):
        mock_packet_logger = MagicMock()
        mock_get_logger.return_value = mock_packet_logger

        _mock_config.load_incluster_config.return_value = None
        _mock_config.ConfigException = Exception

        _mock_k8s_client.ApiClient.return_value = MagicMock()
        _mock_k8s_client.CoreV1Api.return_value = MagicMock()
        _mock_k8s_client.BatchV1Api.return_value = MagicMock()
        _mock_k8s_client.NetworkingV1Api.return_value = MagicMock()

        from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
            KubernetesSandboxManager,
        )

        KubernetesSandboxManager._instance = None
        mgr = KubernetesSandboxManager()

        yield mgr

        KubernetesSandboxManager._instance = None


# ---------------------------------------------------------------------------
# Tests: Shared client lifecycle
# ---------------------------------------------------------------------------


def test_send_message_creates_shared_client_on_first_call(manager: Any) -> None:
    """First call to send_message() should create one shared ACPExecClient
    for the sandbox, create an ACP session, and yield events."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()
    message = "hello world"

    mock_event = _make_mock_event()
    mock_client = _make_mock_client(is_running=True)
    acp_session_id = "acp-session-abc"
    mock_client.get_or_create_session.return_value = acp_session_id
    # session_ids must include the created session for validation
    type(mock_client).session_ids = property(lambda _: [acp_session_id])
    mock_client.send_message.return_value = iter([mock_event])

    with patch(_ACP_CLIENT_CLASS, return_value=mock_client) as MockClass:
        events = _drain_generator(manager.send_message(sandbox_id, session_id, message))

    # Verify shared client was constructed once
    MockClass.assert_called_once()

    # Verify start() was called with /workspace (not session-specific path)
    mock_client.start.assert_called_once_with(cwd="/workspace")

    # Verify get_or_create_session was called with the session path
    expected_cwd = f"/workspace/sessions/{session_id}"
    mock_client.get_or_create_session.assert_called_once_with(cwd=expected_cwd)

    # Verify send_message was called with correct args
    mock_client.send_message.assert_called_once_with(message, session_id=acp_session_id)

    # Verify we got the event
    assert mock_event in events

    # Verify shared client is cached by sandbox_id
    assert sandbox_id in manager._acp_clients
    assert manager._acp_clients[sandbox_id] is mock_client

    # Verify session mapping exists
    assert (sandbox_id, session_id) in manager._acp_session_ids
    assert manager._acp_session_ids[(sandbox_id, session_id)] == acp_session_id


def test_send_message_reuses_shared_client_for_same_session(manager: Any) -> None:
    """Second call with the same session should reuse the shared client
    and the same ACP session ID."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()

    mock_event_1 = _make_mock_event()
    mock_event_2 = _make_mock_event()
    mock_client = _make_mock_client(is_running=True)
    acp_session_id = "acp-session-reuse"
    mock_client.get_or_create_session.return_value = acp_session_id
    type(mock_client).session_ids = property(lambda _: [acp_session_id])

    mock_client.send_message.side_effect = [
        iter([mock_event_1]),
        iter([mock_event_2]),
    ]

    with patch(_ACP_CLIENT_CLASS, return_value=mock_client) as MockClass:
        events_1 = _drain_generator(
            manager.send_message(sandbox_id, session_id, "first")
        )
        events_2 = _drain_generator(
            manager.send_message(sandbox_id, session_id, "second")
        )

    # Constructor called only ONCE (shared client)
    MockClass.assert_called_once()

    # start() called only once
    mock_client.start.assert_called_once()

    # get_or_create_session called only once (second call uses cached mapping)
    mock_client.get_or_create_session.assert_called_once()

    # send_message called twice with same ACP session ID
    assert mock_client.send_message.call_count == 2

    assert mock_event_1 in events_1
    assert mock_event_2 in events_2


def test_send_message_different_sessions_share_client(manager: Any) -> None:
    """Two different craft sessions on the same sandbox should share the
    same ACPExecClient but have different ACP sessions."""
    sandbox_id: UUID = uuid4()
    session_id_a: UUID = uuid4()
    session_id_b: UUID = uuid4()

    mock_client = _make_mock_client(is_running=True)
    acp_session_a = "acp-session-a"
    acp_session_b = "acp-session-b"
    mock_client.get_or_create_session.side_effect = [acp_session_a, acp_session_b]
    type(mock_client).session_ids = property(lambda _: [acp_session_a, acp_session_b])

    mock_event_a = _make_mock_event()
    mock_event_b = _make_mock_event()
    mock_client.send_message.side_effect = [
        iter([mock_event_a]),
        iter([mock_event_b]),
    ]

    with patch(_ACP_CLIENT_CLASS, return_value=mock_client) as MockClass:
        events_a = _drain_generator(
            manager.send_message(sandbox_id, session_id_a, "msg a")
        )
        events_b = _drain_generator(
            manager.send_message(sandbox_id, session_id_b, "msg b")
        )

    # Only ONE shared client was created
    MockClass.assert_called_once()

    # get_or_create_session called twice (once per craft session)
    assert mock_client.get_or_create_session.call_count == 2

    # send_message called with different ACP session IDs
    mock_client.send_message.assert_any_call("msg a", session_id=acp_session_a)
    mock_client.send_message.assert_any_call("msg b", session_id=acp_session_b)

    # Both session mappings exist
    assert manager._acp_session_ids[(sandbox_id, session_id_a)] == acp_session_a
    assert manager._acp_session_ids[(sandbox_id, session_id_b)] == acp_session_b

    assert mock_event_a in events_a
    assert mock_event_b in events_b


def test_send_message_replaces_dead_client(manager: Any) -> None:
    """If the shared client has is_running == False, should replace it and
    re-create sessions."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()

    # Place a dead client in the cache
    dead_client = _make_mock_client(is_running=False)
    manager._acp_clients[sandbox_id] = dead_client
    manager._acp_session_ids[(sandbox_id, session_id)] = "old-acp-session"

    # Create the replacement client
    new_event = _make_mock_event()
    new_client = _make_mock_client(is_running=True)
    new_acp_session = "new-acp-session"
    new_client.get_or_create_session.return_value = new_acp_session
    type(new_client).session_ids = property(lambda _: [new_acp_session])
    new_client.send_message.return_value = iter([new_event])

    with patch(_ACP_CLIENT_CLASS, return_value=new_client):
        events = _drain_generator(manager.send_message(sandbox_id, session_id, "test"))

    # Dead client was stopped during replacement
    dead_client.stop.assert_called_once()

    # New client was started
    new_client.start.assert_called_once()

    # Old session mapping was cleared, new one created
    assert manager._acp_session_ids[(sandbox_id, session_id)] == new_acp_session

    # Cache holds the new client
    assert manager._acp_clients[sandbox_id] is new_client

    assert new_event in events


# ---------------------------------------------------------------------------
# Tests: Cleanup
# ---------------------------------------------------------------------------


def test_terminate_stops_shared_client(manager: Any) -> None:
    """terminate(sandbox_id) should stop the shared client and clear
    all session mappings for that sandbox."""
    sandbox_id: UUID = uuid4()
    session_id_1: UUID = uuid4()
    session_id_2: UUID = uuid4()

    mock_client = _make_mock_client(is_running=True)
    manager._acp_clients[sandbox_id] = mock_client
    manager._acp_session_ids[(sandbox_id, session_id_1)] = "acp-1"
    manager._acp_session_ids[(sandbox_id, session_id_2)] = "acp-2"

    with patch.object(manager, "_cleanup_kubernetes_resources"):
        manager.terminate(sandbox_id)

    # Shared client was stopped
    mock_client.stop.assert_called_once()

    # Client removed from cache
    assert sandbox_id not in manager._acp_clients

    # Session mappings removed
    assert (sandbox_id, session_id_1) not in manager._acp_session_ids
    assert (sandbox_id, session_id_2) not in manager._acp_session_ids


def test_terminate_leaves_other_sandbox_untouched(manager: Any) -> None:
    """terminate(sandbox_A) should NOT affect sandbox_B's client or sessions."""
    sandbox_a: UUID = uuid4()
    sandbox_b: UUID = uuid4()
    session_a: UUID = uuid4()
    session_b: UUID = uuid4()

    client_a = _make_mock_client(is_running=True)
    client_b = _make_mock_client(is_running=True)

    manager._acp_clients[sandbox_a] = client_a
    manager._acp_clients[sandbox_b] = client_b
    manager._acp_session_ids[(sandbox_a, session_a)] = "acp-a"
    manager._acp_session_ids[(sandbox_b, session_b)] = "acp-b"

    with patch.object(manager, "_cleanup_kubernetes_resources"):
        manager.terminate(sandbox_a)

    # sandbox_a cleaned up
    client_a.stop.assert_called_once()
    assert sandbox_a not in manager._acp_clients
    assert (sandbox_a, session_a) not in manager._acp_session_ids

    # sandbox_b untouched
    client_b.stop.assert_not_called()
    assert sandbox_b in manager._acp_clients
    assert manager._acp_session_ids[(sandbox_b, session_b)] == "acp-b"


def test_cleanup_session_removes_session_mapping(manager: Any) -> None:
    """cleanup_session_workspace() should remove the session mapping but
    leave the shared client alive for other sessions."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()

    mock_client = _make_mock_client(is_running=True)
    manager._acp_clients[sandbox_id] = mock_client
    manager._acp_session_ids[(sandbox_id, session_id)] = "acp-session-xyz"

    with patch.object(manager, "_stream_core_api") as mock_stream_api:
        mock_stream_api.connect_get_namespaced_pod_exec = MagicMock()
        with patch(f"{_K8S_MODULE}.k8s_stream", return_value="cleanup ok"):
            manager.cleanup_session_workspace(sandbox_id, session_id)

    # Session mapping removed
    assert (sandbox_id, session_id) not in manager._acp_session_ids

    # Shared client is NOT stopped (other sessions may use it)
    mock_client.stop.assert_not_called()
    assert sandbox_id in manager._acp_clients


def test_cleanup_session_handles_no_mapping(manager: Any) -> None:
    """cleanup_session_workspace() should not error when there's no
    session mapping."""
    sandbox_id: UUID = uuid4()
    session_id: UUID = uuid4()

    assert (sandbox_id, session_id) not in manager._acp_session_ids

    with patch.object(manager, "_stream_core_api") as mock_stream_api:
        mock_stream_api.connect_get_namespaced_pod_exec = MagicMock()
        with patch(f"{_K8S_MODULE}.k8s_stream", return_value="cleanup ok"):
            manager.cleanup_session_workspace(sandbox_id, session_id)

    assert (sandbox_id, session_id) not in manager._acp_session_ids
