"""Stream error semantics tests (HTTP half).

These tests drive the ``/build/sessions/{id}/send-message`` SSE endpoint and
inspect the packet sequence the consumer actually sees. They run against a
real Onyx deployment using :class:`BuildSessionManager`.

Behaviors that require failure injection (mid-stream exceptions, turn
timeout, SSEKeepalive emission) are exercised in the ext-dep suite at
``tests/external_dependency_unit/craft/test_streaming_persistence.py``
where the sandbox manager can be stubbed.
"""

from __future__ import annotations

import uuid

import httpx

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


def _drain_packets(user: DATestUser, session_id: uuid.UUID) -> list[dict]:
    """Drive the SSE stream to completion and collect every JSON packet."""
    packets: list[dict] = []
    try:
        for packet in BuildSessionManager.send_message(user, session_id, "hello"):
            packets.append(packet)
    except httpx.RemoteProtocolError:
        # Server closed the stream after emitting the terminal ErrorPacket;
        # whatever made it through is already in ``packets``.
        pass
    return packets


def test_sandbox_not_running_emits_error_packet_and_closes(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001 — ensure default LLM exists
) -> None:
    """A non-RUNNING sandbox short-circuits the stream with an ErrorPacket.

    Path under test (``manager.py::send_message``):
        if not sandbox or sandbox.status != SandboxStatus.RUNNING:
            yield ErrorPacket("Sandbox is not running. Please wait for it to start.")
            return

    We provision a session (so a sandbox exists), then call
    ``/build/sandbox/reset`` to mark it ``TERMINATED`` — a non-RUNNING status.
    The next send-message must yield exactly one error packet and end.
    """
    body = BuildSessionManager.create(admin_user)
    session_id = uuid.UUID(body["id"])

    # Force the sandbox out of RUNNING. Reset transitions it to TERMINATED.
    reset_response = client.post(
        f"{API_SERVER_URL}/build/sandbox/reset",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert reset_response.status_code == 204

    packets = _drain_packets(admin_user, session_id)

    assert packets, "Expected at least one packet on the stream"
    first = packets[0]
    assert first.get("type") == "error"
    assert "not running" in first.get("message", "").lower()
    # Stream closes right after the ErrorPacket — no further events allowed.
    assert all(p.get("type") == "error" for p in packets)


def test_session_not_found_emits_error_packet(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Streaming against another user's session id yields an ErrorPacket.

    Important: the SSE generator catches "session belongs to someone else"
    inside the manager and emits ErrorPacket("Session not found") *on the
    stream*, not via the HTTP status. This is deliberate — the FE relies on
    the in-stream packet to render the error, since the SSE endpoint has
    already returned a 200 to the client by the time the check runs.
    """
    body = BuildSessionManager.create(admin_user)
    session_id = uuid.UUID(body["id"])

    other_user = UserManager.create(name=f"otheruser-{uuid.uuid4().hex[:8]}")

    packets = _drain_packets(other_user, session_id)

    assert packets, "Expected at least one packet on the stream"
    error_packet = next((p for p in packets if p.get("type") == "error"), None)
    assert error_packet is not None
    assert error_packet["message"] == "Session not found"
