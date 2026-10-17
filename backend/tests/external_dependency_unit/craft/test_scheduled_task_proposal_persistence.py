"""The scheduled-task proposal card is rendered from the persisted tool call,
and its approval is recorded back onto that same message. Both rest on one
property of existing code: a completed tool call persists its arguments and
its raw tool name into ``build_message.message_metadata``.

These tests pin that property through the real emitter and the real
persistence path, so the design fails loudly here rather than silently in the
UI if either changes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import BuildMessage, BuildSession
from onyx.server.features.build.sandbox.event_schema import ToolCallProgress
from onyx.server.features.build.sandbox.opencode.serve_client import (
    _emit_tool_events,
    _TurnState,
)
from onyx.server.features.build.session.streaming import (
    BuildStreamingState,
    persist_sandbox_event,
)

PROPOSAL_TOOL = "propose_scheduled_task"


# What opencode publishes for a completed call to the proposal tool.
def _completed_part(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "callID": "call_proposal_1",
        "tool": PROPOSAL_TOOL,
        "state": {"status": "completed", "input": args},
    }


def _proposal_args() -> dict[str, Any]:
    return {
        "name": "Weekday backlog digest",
        "prompt": "Check my Linear backlog and summarise what moved.",
        "schedule": {
            "mode": "daily_weekly",
            "time_of_day": "09:00",
            "weekdays": [1, 2, 3, 4, 5],
        },
    }


def test_emitter_carries_tool_name_and_args() -> None:
    """The raw tool name rides in ``_meta``, not ``title``.

    ``_tool_title`` maps unknown tools to "Running tool", so anything matching
    on the title would never fire for a plugin-declared tool.
    """
    args = _proposal_args()
    events = list(
        _emit_tool_events(_completed_part(args), _TurnState(session_id="oc-session"))
    )
    progress = [e for e in events if isinstance(e, ToolCallProgress)]
    assert progress, "a completed part must emit a ToolCallProgress"

    dumped = progress[-1].model_dump(mode="json", by_alias=True, exclude_none=False)
    assert dumped["_meta"]["toolName"] == PROPOSAL_TOOL
    assert dumped["title"] != PROPOSAL_TOOL
    assert dumped["rawInput"] == args
    assert dumped["toolCallId"] == "call_proposal_1"


def test_completed_tool_call_persists_args_and_tool_name(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session: BuildSession,
) -> None:
    """The proposal's contents reach Postgres without any new schema."""
    args = _proposal_args()
    events = list(
        _emit_tool_events(_completed_part(args), _TurnState(session_id="oc-session"))
    )
    progress = [e for e in events if isinstance(e, ToolCallProgress)][-1]

    state = BuildStreamingState(turn_index=0)
    persist_sandbox_event(db_session, build_session.id, state, progress)
    db_session.commit()

    stored = (
        db_session.execute(
            select(BuildMessage).where(BuildMessage.session_id == build_session.id)
        )
        .scalars()
        .all()
    )
    tool_calls = [
        m for m in stored if m.message_metadata.get("type") == "tool_call_progress"
    ]
    assert len(tool_calls) == 1

    metadata = tool_calls[0].message_metadata
    assert metadata["_meta"]["toolName"] == PROPOSAL_TOOL
    assert metadata["rawInput"] == args
    assert metadata["toolCallId"] == "call_proposal_1"


def test_pending_tool_call_does_not_persist(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session: BuildSession,
) -> None:
    """Only terminal calls persist, so the card never renders a half-made
    proposal from a call still in flight."""
    part = _completed_part(_proposal_args())
    part["state"]["status"] = "pending"
    for event in _emit_tool_events(part, _TurnState(session_id="oc-session")):
        persist_sandbox_event(
            db_session, build_session.id, BuildStreamingState(turn_index=0), event
        )
    db_session.commit()

    stored = (
        db_session.execute(
            select(BuildMessage).where(BuildMessage.session_id == build_session.id)
        )
        .scalars()
        .all()
    )
    assert [
        m for m in stored if m.message_metadata.get("type") == "tool_call_progress"
    ] == []
