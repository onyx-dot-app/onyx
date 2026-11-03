"""Tests for live attach stream text coalescing in serve transport."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest

from onyx.server.features.build.packets import SubagentStartedPacket
from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.event_schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    PromptResponse,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus
from onyx.server.features.build.sandbox.serve_transport import ServeConnectionInfo

_DIRECTORY = "/workspace/sessions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_SESSION = "ses_test"


@pytest.fixture
def mgr(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[KubernetesSandboxManager, None, None]:
    monkeypatch.setattr(PodEventBus, "_ensure_reader_started", lambda _: None)

    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    manager._init_serve_state()
    manager._load_serve_connection_info = (  # ty: ignore[invalid-assignment]
        lambda sandbox_id: ServeConnectionInfo(
            base_url=f"http://{sandbox_id}.invalid:4096",
            password=None,
        )
    )

    try:
        yield manager
    finally:
        with manager._event_buses_lock:
            buses = list(manager._event_buses.values())
            manager._event_buses.clear()
        for bus in buses:
            bus.close()


def _wait_for(predicate: Any, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _dispatch_assistant_text_delta(bus: PodEventBus, text: str) -> None:
    bus._dispatch(
        {
            "type": "message.part.delta",
            "properties": {
                "sessionID": _SESSION,
                "messageID": "msg1",
                "partID": "part1",
                "field": "text",
                "delta": text,
            },
        }
    )


def test_subscribe_to_opencode_session_coalesces_adjacent_text_deltas(
    mgr: KubernetesSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve_transport, "LIVE_TEXT_COALESCE_SECONDS", 0.01)
    sandbox_id = uuid4()
    bus = PodEventBus(
        base_url=f"http://{sandbox_id}.invalid:4096",
        auth=None,
        directory=_DIRECTORY,
    )
    with mgr._event_buses_lock:
        mgr._event_buses[(sandbox_id, _DIRECTORY)] = bus
    events: list[Any] = []

    def reader() -> None:
        for event in mgr.subscribe_to_opencode_session(
            sandbox_id,
            _SESSION,
            directory=_DIRECTORY,
            keepalive_seconds=60.0,
        ):
            events.append(event)
            if isinstance(event, PromptResponse):
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    assert _wait_for(lambda: bool(bus._subscribers.get(_SESSION)))

    bus._dispatch(
        {
            "type": "message.updated",
            "properties": {
                "sessionID": _SESSION,
                "info": {
                    "id": "msg1",
                    "sessionID": _SESSION,
                    "role": "assistant",
                },
            },
        }
    )
    bus._dispatch(
        {
            "type": "message.part.updated",
            "properties": {
                "sessionID": _SESSION,
                "part": {
                    "id": "part1",
                    "messageID": "msg1",
                    "sessionID": _SESSION,
                    "type": "text",
                    "text": "",
                    "state": {"status": "active"},
                },
            },
        }
    )
    _dispatch_assistant_text_delta(bus, "Hel")
    _dispatch_assistant_text_delta(bus, "lo")
    bus._dispatch(
        {
            "type": "message.part.updated",
            "properties": {
                "sessionID": _SESSION,
                "part": {
                    "id": "part1",
                    "messageID": "msg1",
                    "type": "text",
                    "text": "Hello",
                },
            },
        }
    )
    bus._dispatch(
        {
            "type": "session.idle",
            "properties": {"sessionID": _SESSION},
        }
    )

    thread.join(timeout=3.0)
    assert not thread.is_alive()

    assert len(events) == 3
    assert isinstance(events[0], AgentMessageChunk)
    assert getattr(events[0].content, "text", None) == "Hello"  # ods: ignore[getattr]
    assert events[0].model_dump(by_alias=True)["_meta"] == {"partId": "part1"}
    assert isinstance(events[1], AgentMessageChunk)
    assert events[1].content.text == ""
    assert events[1].model_dump(by_alias=True)["_meta"] == {
        "partId": "part1",
        "snapshotText": "Hello",
    }
    assert isinstance(events[2], PromptResponse)


def test_subscribe_to_opencode_session_forwards_child_events(
    mgr: KubernetesSandboxManager,
) -> None:
    sandbox_id = uuid4()
    child_session = "ses_child"
    bus = PodEventBus(
        base_url=f"http://{sandbox_id}.invalid:4096",
        auth=None,
        directory=_DIRECTORY,
    )
    with mgr._event_buses_lock:
        mgr._event_buses[(sandbox_id, _DIRECTORY)] = bus
    events: list[Any] = []

    def reader() -> None:
        for event in mgr.subscribe_to_opencode_session(
            sandbox_id,
            _SESSION,
            directory=_DIRECTORY,
            keepalive_seconds=60.0,
        ):
            events.append(event)
            if isinstance(event, PromptResponse):
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    assert _wait_for(lambda: bool(bus._subscribers.get(_SESSION)))

    bus._dispatch(
        {
            "type": "session.created",
            "properties": {
                "sessionID": child_session,
                "info": {"id": child_session, "parentID": _SESSION},
            },
        }
    )
    bus._dispatch(
        {
            "type": "message.updated",
            "properties": {
                "sessionID": child_session,
                "info": {
                    "id": "msg_child",
                    "sessionID": child_session,
                    "role": "assistant",
                },
            },
        }
    )
    bus._dispatch(
        {
            "type": "message.part.delta",
            "properties": {
                "sessionID": child_session,
                "messageID": "msg_child",
                "partID": "part_child",
                "field": "text",
                "delta": "child streamed text",
            },
        }
    )
    bus._dispatch(
        {
            "type": "session.idle",
            "properties": {"sessionID": _SESSION},
        }
    )

    thread.join(timeout=3.0)
    assert not thread.is_alive()

    assert any(isinstance(event, SubagentStartedPacket) for event in events)
    child_chunks = [event for event in events if isinstance(event, AgentMessageChunk)]
    assert len(child_chunks) == 1
    assert (
        getattr(child_chunks[0].content, "text", None)  # ods: ignore[getattr]
        == "child streamed text"
    )
    assert child_chunks[0].field_meta == {
        "partId": "part_child",
        "sessionId": child_session,
        "parentSessionId": _SESSION,
    }
    assert isinstance(events[-1], PromptResponse)


@pytest.mark.parametrize("event_class", [AgentMessageChunk, AgentThoughtChunk])
def test_live_text_coalescing_preserves_part_and_snapshot_boundaries(
    event_class: type[AgentMessageChunk] | type[AgentThoughtChunk],
) -> None:
    def chunk(
        text: str, metadata: dict[str, str]
    ) -> AgentMessageChunk | AgentThoughtChunk:
        return event_class.model_validate(
            {
                "sessionUpdate": "agent_message_chunk"
                if event_class is AgentMessageChunk
                else "agent_thought_chunk",
                "content": {"type": "text", "text": text},
                "_meta": metadata,
            }
        )

    pending = chunk("Hello", {"partId": "part1"})
    merged = serve_transport._merge_text_chunk(
        pending, chunk(" world", {"partId": "part1"})
    )
    assert isinstance(merged, event_class)
    assert merged.content.text == "Hello world"
    assert merged.field_meta == {"partId": "part1"}
    assert (
        serve_transport._merge_text_chunk(pending, chunk("next", {"partId": "part2"}))
        is None
    )
    snapshot = chunk("", {"partId": "part1", "snapshotText": "Hello world"})
    assert serve_transport._merge_text_chunk(pending, snapshot) is None
    assert serve_transport._merge_text_chunk(snapshot, snapshot) is None
