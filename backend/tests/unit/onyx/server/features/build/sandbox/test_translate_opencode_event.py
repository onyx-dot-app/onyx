"""Unit tests for ``translate_opencode_event``.

Pure-function tests against canned opencode ``/event`` payloads. Locks
the observed wire contract so regressions surface here. No network, no
subprocess, no real opencode serve.
"""

from __future__ import annotations

from typing import Any

import pytest

from onyx.server.features.build.packets import CompactionPacket
from onyx.server.features.build.packets import ContextUsagePacket
from onyx.server.features.build.packets import SubagentStartedPacket
from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import Error
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.event_schema import ToolCallProgress
from onyx.server.features.build.sandbox.event_schema import ToolCallStart
from onyx.server.features.build.sandbox.opencode.serve_client import (
    _synthesize_tool_content,
)
from onyx.server.features.build.sandbox.opencode.serve_client import _tool_status
from onyx.server.features.build.sandbox.opencode.serve_client import _TurnState
from onyx.server.features.build.sandbox.opencode.serve_client import _wrap_raw_output
from onyx.server.features.build.sandbox.opencode.serve_client import (
    translate_opencode_event,
)

SESS = "ses_test123"


def _state() -> _TurnState:
    return _TurnState(session_id=SESS)


def _fetch_from(
    responses: dict[str, dict[str, Any] | None],
) -> tuple[Any, list[str]]:
    """Dict-backed ``fetch_message`` stub. Returns the callable and a
    shared list that records each call so tests can assert hydrate
    happened exactly once per messageID."""
    calls: list[str] = []

    def fetch(msg_id: str) -> dict[str, Any] | None:
        calls.append(msg_id)
        return responses.get(msg_id)

    return fetch, calls


def _drain(events: Any) -> list[Any]:
    """Translation returns an Iterable; flatten to list for assertions."""
    return list(events)


# ───────────────────────── text deltas ────────────────────────────


def _assistant_state() -> _TurnState:
    """State pre-populated as if we'd already seen the assistant
    message.updated event. Most text-related tests start here."""
    s = _state()
    s.assistant_message_ids.add("msg_assistant")
    return s


def test_text_delta_yields_agent_message_chunk() -> None:
    s = _assistant_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_assistant",
                    "partID": "p1",
                    "field": "text",
                    "delta": "hello",
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], AgentMessageChunk)
    assert out[0].content.text == "hello"  # type: ignore[union-attr]
    assert s.local_text == {"p1": "hello"}


def test_text_delta_accumulates_into_local() -> None:
    s = _assistant_state()
    for part in ["foo", " bar", " baz"]:
        _drain(
            translate_opencode_event(
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": SESS,
                        "messageID": "msg_assistant",
                        "partID": "p1",
                        "field": "text",
                        "delta": part,
                    },
                },
                s,
            )
        )
    assert s.local_text["p1"] == "foo bar baz"


def test_reasoning_delta_yields_agent_thought_chunk() -> None:
    """Deltas on a part of ``type=reasoning`` become AgentThoughtChunk.

    NOTE: opencode emits the delta with ``field=text`` (the part's text
    attribute) regardless of whether the part is reasoning or visible
    text — what differentiates them is the PART's type, which we learn
    from a prior ``message.part.updated`` event. The translator looks up
    the part type in ``state.part_types``."""
    s = _assistant_state()
    s.part_types["p1"] = "reasoning"
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_assistant",
                    "partID": "p1",
                    "field": "text",  # ← yes, "text" even for reasoning parts
                    "delta": "thinking...",
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], AgentThoughtChunk)


def test_empty_reasoning_delta_is_ignored() -> None:
    """Anthropic can emit an empty reasoning delta when adaptive thinking
    display is omitted. Empty thought packets should not be surfaced to Craft."""
    s = _assistant_state()
    s.part_types["p1"] = "reasoning"

    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_assistant",
                    "partID": "p1",
                    "field": "text",
                    "delta": "",
                },
            },
            s,
        )
    )

    assert out == []
    assert "p1" not in s.local_text


def test_reasoning_part_type_recorded_from_part_updated() -> None:
    """A ``message.part.updated`` with ``type=reasoning`` should register
    the part's type so subsequent deltas route to AgentThoughtChunk."""
    s = _assistant_state()
    # Receive the part creation first.
    _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "p_reason",
                        "messageID": "msg_assistant",
                        "type": "reasoning",
                        "text": "",
                    },
                },
            },
            s,
        )
    )
    assert s.part_types["p_reason"] == "reasoning"
    # Now a delta routes via the recorded type.
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_assistant",
                    "partID": "p_reason",
                    "field": "text",
                    "delta": "weighing options",
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], AgentThoughtChunk)


def test_multi_assistant_message_turn_accepts_both() -> None:
    """A turn with a tool call yields ≥2 assistant messages: the initial
    one with thoughts + tool call, and a follow-up with the post-tool
    answer. Both message ids must be tracked, otherwise the follow-up's
    text deltas get dropped — regression test for the web-search bug
    where the model answered after searching but our output showed only
    the pre-tool reasoning."""
    s = _state()
    # First assistant message arrives (pre-tool thoughts + tool call)
    _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "id": "msg_A",
                        "sessionID": SESS,
                        "role": "assistant",
                        "time": {"completed": None},
                    }
                },
            },
            s,
        )
    )
    assert "msg_A" in s.assistant_message_ids
    # Then a follow-up assistant message arrives (post-tool answer)
    _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "id": "msg_B",
                        "sessionID": SESS,
                        "role": "assistant",
                        "time": {"completed": None},
                    }
                },
            },
            s,
        )
    )
    assert "msg_B" in s.assistant_message_ids
    # Register a text part on msg_B
    _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "p_answer",
                        "messageID": "msg_B",
                        "type": "text",
                        "text": "",
                    },
                },
            },
            s,
        )
    )
    # Delta on msg_B's text part should NOT be filtered.
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_B",
                    "partID": "p_answer",
                    "field": "text",
                    "delta": "Yuhong",
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], AgentMessageChunk)
    assert out[0].content.text == "Yuhong"  # type: ignore[union-attr]


def test_step_part_delta_ignored() -> None:
    """Deltas on parts that aren't text/reasoning (e.g. step-start,
    step-finish, tool) shouldn't surface user-visible events."""
    s = _assistant_state()
    s.part_types["p_step"] = "step-start"
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_assistant",
                    "partID": "p_step",
                    "field": "text",
                    "delta": "step boundary",
                },
            },
            s,
        )
    )
    assert out == []


def test_unknown_field_delta_ignored() -> None:
    s = _assistant_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_assistant",
                    "partID": "p1",
                    "field": "tool_call",
                    "delta": "ignored",
                },
            },
            s,
        )
    )
    assert out == []


# ───────────────────────── session filtering ──────────────────────


def test_event_for_other_session_filtered() -> None:
    s = _assistant_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": "ses_OTHER",
                    "messageID": "msg_assistant",
                    "partID": "p1",
                    "field": "text",
                    "delta": "hello",
                },
            },
            s,
        )
    )
    assert out == []
    assert s.local_text == {}


def test_message_updated_with_session_in_info_caches_role() -> None:
    s = _state()
    # Some events nest sessionID inside properties.info; verify the filter
    # still recognizes the session AND that we cache role=assistant even
    # though message.updated alone never yields a terminator.
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "id": "msg_abc",
                        "role": "assistant",
                        "time": {"completed": 1779000000000},
                        "finish": "stop",
                    }
                },
            },
            s,
        )
    )
    assert out == []
    assert "msg_abc" in s.assistant_message_ids


# ───────────────────────── turn terminators ───────────────────────


def test_message_updated_alone_does_not_terminate() -> None:
    # Opencode fires message.updated with time.completed at EVERY step end
    # (tool-call step, text step, ...). It's not a turn-level signal.
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "role": "assistant",
                        "time": {"completed": 1779000000000},
                        "finish": "stop",
                    }
                },
            },
            s,
        )
    )
    assert out == []


def test_session_idle_terminates_once() -> None:
    s = _state()
    out1 = _drain(
        translate_opencode_event(
            {"type": "session.idle", "properties": {"sessionID": SESS}}, s
        )
    )
    assert len(out1) == 1
    assert isinstance(out1[0], PromptResponse)

    out2 = _drain(
        translate_opencode_event(
            {
                "type": "session.status",
                "properties": {"sessionID": SESS, "status": {"type": "idle"}},
            },
            s,
        )
    )
    assert out2 == []


def test_session_status_idle_object_is_terminator() -> None:
    # status is an object {type: "idle"|"busy"|...} — match on .type.
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "session.status",
                "properties": {"sessionID": SESS, "status": {"type": "idle"}},
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], PromptResponse)


def test_session_status_non_idle_is_noop() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "session.status",
                "properties": {"sessionID": SESS, "status": {"type": "busy"}},
            },
            s,
        )
    )
    assert out == []


def test_user_message_updated_does_not_terminate() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "role": "user",
                        "time": {"completed": 1779000000000},
                    }
                },
            },
            s,
        )
    )
    assert out == []


def test_in_progress_assistant_message_updated_is_noop() -> None:
    # Companion to `test_message_updated_alone_does_not_terminate`: the
    # in-progress variant (time.completed is None) also never terminates.
    # message.updated is never a turn-level signal regardless of completed.
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "role": "assistant",
                        "time": {"completed": None},
                    }
                },
            },
            s,
        )
    )
    assert out == []


def test_finish_stop_maps_to_end_turn() -> None:
    # Finish reason is recorded on message.updated and consumed by
    # the terminator on the subsequent session.idle.
    s = _state()
    _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "role": "assistant",
                        "finish": "stop",
                    }
                },
            },
            s,
        )
    )
    out = _drain(
        translate_opencode_event(
            {"type": "session.idle", "properties": {"sessionID": SESS}}, s
        )
    )
    assert isinstance(out[0], PromptResponse)
    assert out[0].stop_reason == "end_turn"


def test_finish_max_tokens_passes_through() -> None:
    s = _state()
    _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "role": "assistant",
                        "finish": "max_tokens",
                    }
                },
            },
            s,
        )
    )
    out = _drain(
        translate_opencode_event(
            {"type": "session.idle", "properties": {"sessionID": SESS}}, s
        )
    )
    assert isinstance(out[0], PromptResponse)
    assert out[0].stop_reason == "max_tokens"


# ───────────────────────── errors ─────────────────────────────────


def test_session_error_emits_error_event() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "session.error",
                "properties": {
                    "sessionID": SESS,
                    "error": {
                        "name": "UnknownError",
                        "data": {"message": "Model not found."},
                    },
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], Error)
    assert "Model not found" in out[0].message


def test_message_updated_with_error_emits_error_event() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "role": "assistant",
                        "time": {"completed": 1779000000000},
                        "error": {
                            "name": "UnknownError",
                            "data": {"message": "Model not found."},
                        },
                    }
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], Error)
    assert "Model not found" in out[0].message


def test_message_aborted_emits_cancelled_terminal() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "sessionID": SESS,
                        "role": "assistant",
                        "time": {"completed": 1779000000000},
                        "error": {
                            "name": "MessageAbortedError",
                            "data": {"message": "Aborted"},
                        },
                    }
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], PromptResponse)
    assert out[0].stop_reason == "cancelled"


def test_duplicate_session_error_silenced_after_first() -> None:
    """Opencode fires session.error twice (clean msg, then stack trace).
    Only the first should propagate."""
    s = _state()
    first = _drain(
        translate_opencode_event(
            {
                "type": "session.error",
                "properties": {
                    "sessionID": SESS,
                    "error": {"name": "X", "data": {"message": "first"}},
                },
            },
            s,
        )
    )
    second = _drain(
        translate_opencode_event(
            {
                "type": "session.error",
                "properties": {
                    "sessionID": SESS,
                    "error": {"name": "X", "data": {"message": "second"}},
                },
            },
            s,
        )
    )
    assert len(first) == 1
    assert second == []


# ───────────────────────── gap-fill reconciliation ────────────────


def test_message_part_updated_text_with_more_text_fills_gap() -> None:
    """If part.text is longer than what we've yielded as deltas, emit the
    missing tail."""
    s = _assistant_state()
    s.local_text["p1"] = "Hello, "  # Pretend we've yielded this much
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "p1",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "Hello, world!",
                    },
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], AgentMessageChunk)
    assert out[0].content.text == "world!"  # type: ignore[union-attr]
    assert s.local_text["p1"] == "Hello, world!"


def test_message_part_updated_text_matching_is_noop() -> None:
    s = _assistant_state()
    s.local_text["p1"] = "all set"
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "p1",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "all set",
                    },
                },
            },
            s,
        )
    )
    assert out == []


def test_message_part_updated_text_creating_empty_part_is_noop() -> None:
    s = _assistant_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "p_new",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "",
                    },
                },
            },
            s,
        )
    )
    assert out == []


def test_message_part_updated_text_rewind_keeps_local() -> None:
    """If server's expected < local (shouldn't happen), keep local."""
    s = _assistant_state()
    s.local_text["p1"] = "long string we already yielded"
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "p1",
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "short",
                    },
                },
            },
            s,
        )
    )
    assert out == []
    assert s.local_text["p1"] == "long string we already yielded"


# ───────────────────────── tool calls ─────────────────────────────


def _tool_event(
    call_id: str, tool: str, status: str, **state_extra: Any
) -> dict[str, Any]:
    return {
        "type": "message.part.updated",
        "properties": {
            "sessionID": SESS,
            "part": {
                "id": f"prt_{call_id}",
                "type": "tool",
                "tool": tool,
                "callID": call_id,
                "state": {"status": status, **state_extra},
            },
        },
    }


def test_tool_first_sighting_emits_tool_call_start_only_when_pending() -> None:
    s = _state()
    out = _drain(translate_opencode_event(_tool_event("c1", "bash", "pending"), s))
    assert len(out) == 1
    assert isinstance(out[0], ToolCallStart)
    assert out[0].tool_call_id == "c1"
    assert out[0].kind == "execute"
    assert out[0].title == "Running command"


def test_tool_first_sighting_with_running_emits_start_and_progress() -> None:
    """When the first sighting carries status=running (out-of-order publish),
    follow up with a progress event so the consumer sees both stages.

    Note: opencode's "running" maps to the schema's "in_progress" — the consumer
    sees sandbox-event enum values, not opencode raw ones.
    """
    s = _state()
    out = _drain(
        translate_opencode_event(
            _tool_event("c1", "bash", "running", input={"command": "ls"}), s
        )
    )
    assert len(out) == 2
    assert isinstance(out[0], ToolCallStart)
    assert isinstance(out[1], ToolCallProgress)
    assert out[1].status == "in_progress"


def test_tool_subsequent_updates_emit_progress() -> None:
    s = _state()
    _drain(translate_opencode_event(_tool_event("c1", "bash", "pending"), s))
    out = _drain(
        translate_opencode_event(
            _tool_event(
                "c1",
                "bash",
                "completed",
                input={"command": "ls"},
                output="file1\nfile2\n",
            ),
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], ToolCallProgress)
    assert out[0].status == "completed"
    assert out[0].raw_input == {"command": "ls"}
    assert out[0].raw_output is not None
    # Wrapped: {"output": "file1\nfile2\n"}
    assert out[0].raw_output.get("output") == "file1\nfile2\n"  # type: ignore[union-attr]


def test_tool_kind_mapping() -> None:
    cases = [
        ("bash", "execute"),
        ("read", "read"),
        ("edit", "edit"),
        ("write", "edit"),
        ("grep", "search"),
        ("glob", "search"),
        ("webfetch", "fetch"),
        ("websearch", "search"),
        ("task", "other"),
        ("unknown_tool", "other"),
    ]
    for tool, expected_kind in cases:
        s = _state()
        out = _drain(
            translate_opencode_event(_tool_event(f"c_{tool}", tool, "pending"), s)
        )
        assert len(out) == 1
        assert out[0].kind == expected_kind, (
            f"tool {tool!r} → kind {out[0].kind!r}, expected {expected_kind!r}"
        )


# ───────────────────────── tool content synthesis ─────────────────


def test_edit_tool_synthesizes_diff_content() -> None:
    state = {
        "status": "completed",
        "input": {
            "filePath": "/workspace/sessions/test/a.txt",
            "oldString": "banana",
            "newString": "BANANA",
            "replaceAll": False,
        },
        "output": "Edit applied successfully.",
        "metadata": {},
    }
    content = _synthesize_tool_content("edit", state)
    assert content is not None
    assert len(content) == 1
    assert content[0]["type"] == "diff"
    assert content[0]["path"] == "/workspace/sessions/test/a.txt"
    assert content[0]["oldText"] == "banana"
    assert content[0]["newText"] == "BANANA"


def test_read_tool_synthesizes_content_block() -> None:
    state = {
        "status": "completed",
        "input": {"filePath": "/a.txt", "offset": 0, "limit": 2000},
        "output": "<path>/a.txt</path>\n<content>\n1: foo\n2: bar\n</content>",
    }
    content = _synthesize_tool_content("read", state)
    assert content is not None
    assert content[0]["type"] == "content"
    assert content[0]["content"]["type"] == "text"
    assert "1: foo" in content[0]["content"]["text"]


def test_bash_tool_no_content_synthesis() -> None:
    assert (
        _synthesize_tool_content("bash", {"status": "completed", "input": {}}) is None
    )


def test_task_tool_no_content_synthesis() -> None:
    assert (
        _synthesize_tool_content("task", {"status": "completed", "input": {}}) is None
    )


def test_edit_tool_propagates_through_translation() -> None:
    """End-to-end: edit tool event → ToolCallProgress with synthesized diff."""
    s = _state()
    # Pretend first sighting was already seen
    s.seen_tool_calls.add("c_edit")
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "prt_edit",
                        "type": "tool",
                        "tool": "edit",
                        "callID": "c_edit",
                        "state": {
                            "status": "completed",
                            "input": {
                                "filePath": "/a.txt",
                                "oldString": "x",
                                "newString": "y",
                            },
                            "output": "Edit applied successfully.",
                        },
                    },
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], ToolCallProgress)
    assert out[0].content is not None
    diff_block = out[0].content[0]
    # Pydantic deserialized into FileEditToolCallContent — check its fields
    assert diff_block.type == "diff"  # type: ignore[union-attr]
    assert diff_block.path == "/a.txt"  # type: ignore[union-attr]
    assert diff_block.new_text == "y"  # type: ignore[union-attr]


# ───────────────────────── status mapping ─────────────────────────


@pytest.mark.parametrize(
    "opencode_status, schema_status",
    [
        ("pending", "pending"),
        ("running", "in_progress"),
        ("in_progress", "in_progress"),
        ("completed", "completed"),
        ("failed", "failed"),
        ("error", "failed"),
        ("cancelled", "failed"),
        ("garbage", "pending"),  # unknown defaults to pending
        (None, "pending"),
        (42, "pending"),
    ],
)
def test_tool_status_mapping(opencode_status: Any, schema_status: str) -> None:
    assert _tool_status(opencode_status) == schema_status


# ───────────────────────── raw_output wrapping ────────────────────


def test_wrap_raw_output_string() -> None:
    out = _wrap_raw_output({"output": "result text", "metadata": {"foo": "bar"}})
    assert out is not None
    assert out["output"] == "result text"
    assert out["metadata"] == {"foo": "bar"}


def test_wrap_raw_output_dict_passes_through() -> None:
    payload = {"files": ["a", "b"]}
    out = _wrap_raw_output({"output": payload})
    assert out == payload


def test_wrap_raw_output_none_is_none() -> None:
    assert _wrap_raw_output({"status": "pending"}) is None


# ───────────────────────── role filtering ────────────────────────


def test_text_delta_before_assistant_message_id_known_is_dropped() -> None:
    """Before message.updated(role=assistant), text deltas must be dropped.
    Opencode emits the user's message text part before the assistant
    message is created — accepting these would leak the user prompt into
    the response stream."""
    s = _state()
    # No assistant_message_id set yet
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_unknown",
                    "partID": "p1",
                    "field": "text",
                    "delta": "hi",
                },
            },
            s,
        )
    )
    assert out == []
    assert s.local_text == {}


def test_text_delta_for_user_message_filtered_after_assistant_id_known() -> None:
    s = _state()
    s.assistant_message_ids.add("msg_assistant")
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_user",
                    "partID": "p_user",
                    "field": "text",
                    "delta": "user text",
                },
            },
            s,
        )
    )
    assert out == []
    # Did NOT accumulate
    assert s.local_text == {}


def test_text_delta_for_assistant_message_accepted() -> None:
    s = _state()
    s.assistant_message_ids.add("msg_assistant")
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": SESS,
                    "messageID": "msg_assistant",
                    "partID": "p_asst",
                    "field": "text",
                    "delta": "ok",
                },
            },
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], AgentMessageChunk)


def test_message_updated_assistant_records_id() -> None:
    s = _state()
    _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "info": {
                        "id": "msg_recorded",
                        "sessionID": SESS,
                        "role": "assistant",
                        "time": {"completed": None},
                    }
                },
            },
            s,
        )
    )
    assert "msg_recorded" in s.assistant_message_ids


def test_part_updated_text_for_user_message_filtered() -> None:
    s = _state()
    s.assistant_message_ids.add("msg_assistant")
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": SESS,
                    "part": {
                        "id": "p_user",
                        "messageID": "msg_user",
                        "type": "text",
                        "text": "user echo",
                    },
                },
            },
            s,
        )
    )
    assert out == []


# ───────────────────────── informational events ignored ───────────


@pytest.mark.parametrize(
    "etype",
    [
        "server.connected",
        "server.heartbeat",
        "session.created",
        "session.next.agent.switched",
        "session.next.model.switched",
        "session.diff",
        "session.updated",
        "permission.replied",
        "completely.unknown.event",
    ],
)
def test_informational_events_yield_nothing(etype: str) -> None:
    s = _state()
    out = _drain(
        translate_opencode_event({"type": etype, "properties": {"sessionID": SESS}}, s)
    )
    assert out == []


# ───────────────────────── malformed inputs ───────────────────────


def test_missing_type_ignored() -> None:
    s = _state()
    assert _drain(translate_opencode_event({"properties": {}}, s)) == []


def test_missing_properties_ignored() -> None:
    s = _state()
    assert _drain(translate_opencode_event({"type": "message.updated"}, s)) == []


# ───────────────────────── REST hydrate path ──────────────────────


def _delta_event(msg_id: str, part_id: str = "p1", delta: str = "x") -> dict[str, Any]:
    return {
        "type": "message.part.delta",
        "properties": {
            "sessionID": SESS,
            "messageID": msg_id,
            "partID": part_id,
            "field": "text",
            "delta": delta,
        },
    }


def test_delta_for_unknown_message_hydrates_as_assistant_and_emits() -> None:
    """Happy path for the race fix: a delta arrives before message.updated,
    fetch returns role=assistant, the chunk is emitted, and subsequent
    deltas hit the cached set without re-fetching."""
    s = _state()
    fetch, calls = _fetch_from(
        {
            "msg_new": {
                "info": {"id": "msg_new", "role": "assistant"},
                "parts": [{"id": "p1", "type": "text"}],
            }
        }
    )
    out1 = _drain(
        translate_opencode_event(_delta_event("msg_new", delta="hi "), s, fetch)
    )
    out2 = _drain(
        translate_opencode_event(_delta_event("msg_new", delta="there"), s, fetch)
    )
    assert len(out1) == 1 and isinstance(out1[0], AgentMessageChunk)
    assert len(out2) == 1 and isinstance(out2[0], AgentMessageChunk)
    assert "msg_new" in s.assistant_message_ids
    assert s.part_types["p1"] == "text"
    assert calls == ["msg_new"]


def test_delta_for_unknown_message_hydrates_as_user_and_drops() -> None:
    """Race fix negative path via role classification: fetch returns
    role=user, the delta is dropped and the messageID is cached so the
    next delta short-circuits without re-fetching."""
    s = _state()
    fetch, calls = _fetch_from(
        {"msg_user": {"info": {"id": "msg_user", "role": "user"}, "parts": []}}
    )
    out1 = _drain(translate_opencode_event(_delta_event("msg_user"), s, fetch))
    out2 = _drain(translate_opencode_event(_delta_event("msg_user"), s, fetch))
    assert out1 == [] and out2 == []
    assert "msg_user" in s.user_message_ids
    assert "msg_user" not in s.assistant_message_ids
    assert calls == ["msg_user"]


def test_hydrate_failure_cached_so_subsequent_deltas_skip_fetch() -> None:
    """A failed hydrate (empty fetch, missing info, or unknown role) must
    cache the msg_id as non-assistant so subsequent deltas don't issue
    fresh REST calls — otherwise every delta for a problematic message
    triggers a retry storm on the event-processing hot path."""
    s = _state()
    fetch, calls = _fetch_from({"msg_broken": None})
    for _ in range(2):
        _drain(translate_opencode_event(_delta_event("msg_broken"), s, fetch))
    assert calls == ["msg_broken"]
    assert "msg_broken" in s.user_message_ids


def test_hydrate_unknown_role_cached_negatively() -> None:
    s = _state()
    fetch, calls = _fetch_from(
        {"msg_system": {"info": {"role": "system"}, "parts": []}}
    )
    for _ in range(3):
        _drain(translate_opencode_event(_delta_event("msg_system"), s, fetch))
    assert calls == ["msg_system"]
    assert "msg_system" in s.user_message_ids


def test_hydrate_missing_info_object_cached_negatively() -> None:
    """Defensive: malformed body without an ``info`` dict still caches
    negatively so we don't refetch."""
    s = _state()
    fetch, calls = _fetch_from({"msg_malformed": {"parts": []}})
    for _ in range(2):
        _drain(translate_opencode_event(_delta_event("msg_malformed"), s, fetch))
    assert calls == ["msg_malformed"]
    assert "msg_malformed" in s.user_message_ids


def test_no_fetch_callback_still_caches_to_avoid_repeated_attempts() -> None:
    """If ``fetch_message`` is omitted (e.g. the subagent fanout path),
    the messageID is still cached as non-assistant so subsequent deltas
    don't re-enter the hydrate path."""
    s = _state()
    _drain(translate_opencode_event(_delta_event("msg_no_fetch"), s))
    _drain(translate_opencode_event(_delta_event("msg_no_fetch"), s))
    assert "msg_no_fetch" in s.user_message_ids


def test_non_string_session_id_skips_match() -> None:
    """Defensive: properties.sessionID = None means "no session filter" — the
    event is still considered (some session-wide events have no id)."""
    s = _state()
    out = _drain(
        translate_opencode_event({"type": "session.idle", "properties": {}}, s)
    )
    # session.idle without explicit sessionID still fires terminator
    assert len(out) == 1
    assert isinstance(out[0], PromptResponse)


# ───────────────────────── subagent routing ───────────────────────
# ``parent_resolver`` (child→parent) lets descendant subagent tool events be
# forwarded and tagged with routing metadata. ``children_resolver``
# (parent→children) lets the parent's ``task`` tool event be tagged with the
# subagent session it spawned. Both default to None (old "drop other-session"
# behavior preserved).

PARENT = "ses_PARENT"
CHILD = "ses_CHILD"


def _parent_state() -> _TurnState:
    return _TurnState(session_id=PARENT)


def _child_tool_event(call_id: str = "toolu_x") -> dict[str, Any]:
    """A ``message.part.updated`` tool event emitted by the CHILD session."""
    return {
        "type": "message.part.updated",
        "properties": {
            "sessionID": CHILD,
            "part": {
                "type": "tool",
                "tool": "bash",
                "callID": call_id,
                "state": {
                    "status": "completed",
                    "input": {"command": "echo hi", "description": "d"},
                    "output": "hi\n",
                    "metadata": {"exit": 0},
                },
                "id": "prt_x",
                "sessionID": CHILD,
                "messageID": "msg_x",
            },
        },
    }


def _child_parent_resolver(sess_id: str) -> str | None:
    return PARENT if sess_id == CHILD else None


def test_session_created_emits_subagent_started_for_parent() -> None:
    s = _parent_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "session.created",
                "properties": {
                    "info": {"id": CHILD, "parentID": PARENT},
                },
            },
            s,
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], SubagentStartedPacket)
    assert out[0].subagent_session_id == CHILD
    assert out[0].parent_session_id == PARENT


def test_session_created_for_other_parent_is_ignored() -> None:
    s = _parent_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "session.created",
                "properties": {
                    "info": {"id": CHILD, "parentID": "ses_OTHER"},
                },
            },
            s,
        )
    )

    assert out == []


def test_child_tool_event_forwarded_and_tagged() -> None:
    """A completed tool event from a descendant subagent session is forwarded
    and tagged with sessionId + parentSessionId routing metadata."""
    s = _parent_state()
    out = _drain(
        translate_opencode_event(
            _child_tool_event(),
            s,
            parent_resolver=_child_parent_resolver,
        )
    )
    # First sighting of a completed tool → ToolCallStart then ToolCallProgress.
    assert len(out) == 2
    assert isinstance(out[0], ToolCallStart)
    assert isinstance(out[1], ToolCallProgress)
    assert out[1].status == "completed"
    for event in out:
        meta = event.field_meta
        assert meta is not None
        assert meta["sessionId"] == CHILD
        assert meta["parentSessionId"] == PARENT
        # Existing toolName tag is preserved (merge, not overwrite).
        assert meta["toolName"] == "bash"


def test_child_text_delta_forwarded_and_tagged() -> None:
    """Visible child text should stream into the subagent transcript rather
    than being dropped while the parent task is still running."""
    s = _parent_state()

    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": CHILD,
                    "messageID": "msg_child",
                    "partID": "p_child_text",
                    "field": "text",
                    "delta": "child response",
                },
            },
            s,
            parent_resolver=_child_parent_resolver,
            fetch_message_by_session=lambda session_id, message_id: {
                "info": {
                    "id": message_id,
                    "sessionID": session_id,
                    "role": "assistant",
                },
                "parts": [{"id": "p_child_text", "type": "text"}],
            },
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], AgentMessageChunk)
    assert out[0].content.text == "child response"  # type: ignore[union-attr]
    meta = out[0].field_meta
    assert meta is not None
    assert meta["sessionId"] == CHILD
    assert meta["parentSessionId"] == PARENT


def test_child_reasoning_part_forwarded_and_tagged() -> None:
    s = _parent_state()

    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": CHILD,
                    "part": {
                        "id": "p_child_reasoning",
                        "messageID": "msg_child",
                        "type": "reasoning",
                        "text": "child thinking",
                    },
                },
            },
            s,
            parent_resolver=_child_parent_resolver,
            fetch_message_by_session=lambda session_id, message_id: {
                "info": {
                    "id": message_id,
                    "sessionID": session_id,
                    "role": "assistant",
                },
                "parts": [{"id": "p_child_reasoning", "type": "reasoning"}],
            },
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], AgentThoughtChunk)
    assert out[0].content.text == "child thinking"  # type: ignore[union-attr]
    meta = out[0].field_meta
    assert meta is not None
    assert meta["sessionId"] == CHILD
    assert meta["parentSessionId"] == PARENT


def test_child_reasoning_delta_forwarded_and_tagged() -> None:
    s = _parent_state()

    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": CHILD,
                    "messageID": "msg_child",
                    "partID": "p_child_reasoning",
                    "field": "text",
                    "delta": "child thinking",
                },
            },
            s,
            parent_resolver=_child_parent_resolver,
            fetch_message_by_session=lambda session_id, message_id: {
                "info": {
                    "id": message_id,
                    "sessionID": session_id,
                    "role": "assistant",
                },
                "parts": [{"id": "p_child_reasoning", "type": "reasoning"}],
            },
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], AgentThoughtChunk)
    assert out[0].content.text == "child thinking"  # type: ignore[union-attr]
    meta = out[0].field_meta
    assert meta is not None
    assert meta["sessionId"] == CHILD
    assert meta["parentSessionId"] == PARENT


def test_child_finish_does_not_leak_into_parent_terminator() -> None:
    s = _parent_state()

    _drain(
        translate_opencode_event(
            {
                "type": "message.updated",
                "properties": {
                    "sessionID": CHILD,
                    "info": {
                        "id": "msg_child",
                        "sessionID": CHILD,
                        "role": "assistant",
                        "finish": "max_tokens",
                    },
                },
            },
            s,
            parent_resolver=_child_parent_resolver,
        )
    )
    out = _drain(
        translate_opencode_event(
            {"type": "session.idle", "properties": {"sessionID": PARENT}}, s
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], PromptResponse)
    assert out[0].stop_reason == "end_turn"


def test_child_part_type_does_not_collide_with_parent_part_id() -> None:
    s = _parent_state()

    child_out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": CHILD,
                    "messageID": "msg_child",
                    "partID": "shared_part",
                    "field": "text",
                    "delta": "child thinking",
                },
            },
            s,
            parent_resolver=_child_parent_resolver,
            fetch_message_by_session=lambda session_id, message_id: {
                "info": {
                    "id": message_id,
                    "sessionID": session_id,
                    "role": "assistant",
                },
                "parts": [{"id": "shared_part", "type": "reasoning"}],
            },
        )
    )
    assert isinstance(child_out[0], AgentThoughtChunk)

    s.assistant_message_ids.add("msg_parent")
    parent_out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.delta",
                "properties": {
                    "sessionID": PARENT,
                    "messageID": "msg_parent",
                    "partID": "shared_part",
                    "field": "text",
                    "delta": "parent visible text",
                },
            },
            s,
        )
    )

    assert len(parent_out) == 1
    assert isinstance(parent_out[0], AgentMessageChunk)
    assert parent_out[0].content.text == "parent visible text"  # type: ignore[union-attr]


def test_child_tool_event_dropped_when_not_descendant() -> None:
    """If parent_resolver doesn't link the child to our session, the event is
    dropped (preserving the old other-session behavior)."""
    s = _parent_state()
    out = _drain(
        translate_opencode_event(
            _child_tool_event(),
            s,
            parent_resolver=lambda _s: None,
        )
    )
    assert out == []


def test_other_session_tool_event_dropped_without_parent_resolver() -> None:
    """With parent_resolver omitted (default None), descendant detection is
    impossible → other-session events drop exactly as before."""
    s = _parent_state()
    out = _drain(translate_opencode_event(_child_tool_event(), s))
    assert out == []


def test_parent_task_tool_event_tagged_with_subagent_session() -> None:
    """The parent's own ``task`` tool event is tagged with the subagent session
    it spawned via children_resolver."""
    s = _parent_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": PARENT,
                    "part": {
                        "type": "tool",
                        "tool": "task",
                        "callID": "toolu_t",
                        "state": {
                            "status": "completed",
                            "input": {
                                "description": "explore",
                                "prompt": "Explore the auth code",
                                "subagent_type": "general",
                            },
                        },
                        "id": "prt_t",
                        "sessionID": PARENT,
                        "messageID": "msg_t",
                    },
                },
            },
            s,
            children_resolver=lambda p: [CHILD] if p == PARENT else [],
        )
    )
    assert len(out) >= 1
    for event in out:
        meta = event.field_meta
        assert meta is not None
        assert meta["subagentSessionId"] == CHILD
        assert meta["toolName"] == "task"


def test_parent_non_task_tool_event_not_tagged() -> None:
    """A normal (non-task) parent tool event translates unchanged — no
    subagentSessionId tag even when a children_resolver is supplied."""
    s = _parent_state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "message.part.updated",
                "properties": {
                    "sessionID": PARENT,
                    "part": {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "toolu_b",
                        "state": {
                            "status": "completed",
                            "input": {"command": "ls"},
                        },
                        "id": "prt_b",
                        "sessionID": PARENT,
                        "messageID": "msg_b",
                    },
                },
            },
            s,
            children_resolver=lambda _p: [CHILD],
        )
    )
    assert len(out) >= 1
    for event in out:
        meta = event.field_meta
        assert meta is not None
        assert "subagentSessionId" not in meta
        assert meta["toolName"] == "bash"


# ───────────────────────── exit-code / error-state mapping ────────


def test_bash_completed_with_nonzero_exit_maps_to_failed() -> None:
    s = _state()
    _drain(translate_opencode_event(_tool_event("c1", "bash", "pending"), s))
    out = _drain(
        translate_opencode_event(
            _tool_event(
                "c1",
                "bash",
                "completed",
                input={"command": "sudo do-thing"},
                output="permission denied",
                metadata={"exit": 1},
            ),
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], ToolCallProgress)
    assert out[0].status == "failed"
    assert out[0].raw_output is not None
    assert out[0].raw_output.get("output") == "permission denied"  # type: ignore[union-attr]
    assert out[0].raw_output.get("metadata") == {"exit": 1}  # type: ignore[union-attr]


def test_bash_first_sighting_completed_with_nonzero_exit_dual_emits_failed() -> None:
    """First sighting that already carries completed-with-nonzero-exit state
    emits ToolCallStart plus a ToolCallProgress with the overridden status."""
    s = _state()
    out = _drain(
        translate_opencode_event(
            _tool_event(
                "c1",
                "bash",
                "completed",
                input={"command": "false"},
                output="",
                metadata={"exit": 1},
            ),
            s,
        )
    )
    assert len(out) == 2
    assert isinstance(out[0], ToolCallStart)
    assert isinstance(out[1], ToolCallProgress)
    assert out[1].status == "failed"


def test_bash_completed_with_zero_exit_stays_completed() -> None:
    s = _state()
    _drain(translate_opencode_event(_tool_event("c1", "bash", "pending"), s))
    out = _drain(
        translate_opencode_event(
            _tool_event(
                "c1",
                "bash",
                "completed",
                input={"command": "ls"},
                output="file1\nfile2\n",
                metadata={"exit": 0},
            ),
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], ToolCallProgress)
    assert out[0].status == "completed"


def test_tool_error_state_maps_to_failed_with_error_output() -> None:
    s = _state()
    _drain(translate_opencode_event(_tool_event("c1", "bash", "pending"), s))
    out = _drain(
        translate_opencode_event(
            _tool_event(
                "c1",
                "bash",
                "error",
                error="sudo: a password is required",
            ),
            s,
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], ToolCallProgress)
    assert out[0].status == "failed"
    assert out[0].raw_output is not None
    assert out[0].raw_output.get("output") == "sudo: a password is required"  # type: ignore[union-attr]


def _msg_updated(
    msg_id: str,
    *,
    tokens: dict[str, Any] | None = None,
    cost: float | None = None,
    summary: bool | None = None,
) -> dict[str, Any]:
    info: dict[str, Any] = {"role": "assistant", "id": msg_id, "sessionID": SESS}
    if tokens is not None:
        info["tokens"] = tokens
    if cost is not None:
        info["cost"] = cost
    if summary is not None:
        info["summary"] = summary
    return {"type": "message.updated", "properties": {"info": info}}


_TOKENS = {
    "input": 100,
    "output": 20,
    "reasoning": 5,
    "cache": {"read": 30, "write": 10},
}


def test_message_updated_emits_context_usage() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(_msg_updated("m1", tokens=_TOKENS, cost=0.4), s)
    )
    usage = [e for e in out if isinstance(e, ContextUsagePacket)]
    assert len(usage) == 1
    assert usage[0].used_tokens == 165
    assert usage[0].cost == 0.4


def test_message_updated_no_usage_when_tokens_zero() -> None:
    s = _state()
    zero = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
    out = _drain(translate_opencode_event(_msg_updated("m1", tokens=zero), s))
    assert not [e for e in out if isinstance(e, ContextUsagePacket)]


def test_message_updated_no_usage_without_tokens() -> None:
    s = _state()
    out = _drain(translate_opencode_event(_msg_updated("m1"), s))
    assert not [e for e in out if isinstance(e, ContextUsagePacket)]


def test_summary_message_records_id_and_suppresses_usage() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(_msg_updated("sum1", tokens=_TOKENS, summary=True), s)
    )
    assert "sum1" in s.summary_message_ids
    assert not [e for e in out if isinstance(e, ContextUsagePacket)]


def test_summary_message_text_delta_suppressed() -> None:
    s = _state()
    s.assistant_message_ids.add("sum1")
    s.summary_message_ids.add("sum1")
    delta = {
        "type": "message.part.delta",
        "properties": {
            "field": "text",
            "delta": "This is the summary",
            "partID": "p1",
            "messageID": "sum1",
        },
    }
    assert _drain(translate_opencode_event(delta, s)) == []


def test_session_compacted_emits_marker_with_summary() -> None:
    s = _state()
    s.summary_message_ids.add("sum1")
    fetch, _ = _fetch_from(
        {
            "sum1": {
                "info": {"role": "assistant"},
                "parts": [{"type": "text", "text": "Recap"}],
            }
        }
    )
    out = _drain(
        translate_opencode_event(
            {"type": "session.compacted", "properties": {"sessionID": SESS}},
            s,
            fetch_message=fetch,
        )
    )
    markers = [e for e in out if isinstance(e, CompactionPacket)]
    assert len(markers) == 1
    assert markers[0].summary == "Recap"
