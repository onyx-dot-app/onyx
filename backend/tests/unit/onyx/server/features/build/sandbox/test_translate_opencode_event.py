"""Unit tests for ``translate_opencode_event``.

Pure-function tests against canned opencode ``/event`` payloads. Locks
the wire contract documented in
``docs/craft/opencode-serve-test-report.md`` so regressions surface here.
No network, no subprocess, no real opencode serve.
"""

from __future__ import annotations

from typing import Any

import pytest
from acp.schema import AgentMessageChunk
from acp.schema import AgentThoughtChunk
from acp.schema import Error
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart

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


def test_event_with_session_in_info_node_filtered_correctly() -> None:
    s = _state()
    # Some events nest sessionID inside properties.info
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
    assert len(out) == 1
    assert isinstance(out[0], PromptResponse)


# ───────────────────────── terminator (message.updated) ───────────


def test_terminator_yields_prompt_response_once() -> None:
    s = _state()
    out1 = _drain(
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
    assert len(out1) == 1
    assert isinstance(out1[0], PromptResponse)
    assert out1[0].stop_reason == "end_turn"

    # Backstop signals after the primary should be no-ops.
    out2 = _drain(
        translate_opencode_event(
            {"type": "session.idle", "properties": {"sessionID": SESS}}, s
        )
    )
    assert out2 == []
    out3 = _drain(
        translate_opencode_event(
            {
                "type": "session.status",
                "properties": {"sessionID": SESS, "status": "idle"},
            },
            s,
        )
    )
    assert out3 == []


def test_session_idle_acts_as_backstop_terminator() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(
            {"type": "session.idle", "properties": {"sessionID": SESS}}, s
        )
    )
    assert len(out) == 1
    assert isinstance(out[0], PromptResponse)


def test_session_status_idle_is_terminator() -> None:
    s = _state()
    out = _drain(
        translate_opencode_event(
            {
                "type": "session.status",
                "properties": {"sessionID": SESS, "status": "idle"},
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
                "properties": {"sessionID": SESS, "status": "busy"},
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


def test_assistant_message_without_completed_is_noop() -> None:
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
    assert isinstance(out[0], PromptResponse)
    assert out[0].stop_reason == "end_turn"


def test_finish_max_tokens_passes_through() -> None:
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
                        "finish": "max_tokens",
                    }
                },
            },
            s,
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
    assert isinstance(out[0], Error)
    assert "Aborted" in out[0].message


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

    Note: opencode's "running" maps to ACP's "in_progress" — the consumer
    sees ACP enum values, not opencode raw ones.
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
    "opencode_status, acp_status",
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
def test_tool_status_mapping(opencode_status: Any, acp_status: str) -> None:
    assert _tool_status(opencode_status) == acp_status


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
