"""Encode chat output for ACP and project cached ACP output for the REST API."""

import json
from typing import Any

from acp.helpers import text_block
from acp.schema import AgentMessageChunk, AgentThoughtChunk, UserMessageChunk

from onyx.chat.models import AnswerStreamPart
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    Packet,
    ReasoningDelta,
    StreamCursor,
    UserMessagePacket,
)
from onyx.server.utils import get_json_line


def chat_notification(session_id: str | None, item: dict[str, Any]) -> dict[str, Any]:
    if "obj" in item:
        kind = item["obj"]["type"]
    elif "error" in item:
        kind = "error"
    elif "chat_session_id" in item:
        kind = "session_id"
    elif "next_cursor" in item:
        kind = "stream_cursor"
    else:
        kind = "message_ids"
    return {
        "jsonrpc": "2.0",
        "method": f"_onyx/{kind}",
        "params": {"sessionId": session_id, "packet": item},
    }


def acp_message(
    session_id: str | None, part: AnswerStreamPart | StreamCursor
) -> dict[str, Any]:
    if not isinstance(part, Packet):
        return chat_notification(session_id, part.model_dump(mode="json"))

    obj = part.obj
    tool = part.acp_update
    if tool is not None:
        # Serialize the public result once and preserve nullable Onyx display fields.
        update = tool.model_dump(
            mode="json", by_alias=True, exclude_none=True, exclude={"raw_output"}
        )
    elif isinstance(obj, (AgentResponseDelta, ReasoningDelta, UserMessagePacket)):
        if isinstance(obj, AgentResponseDelta):
            chunk = AgentMessageChunk(
                session_update="agent_message_chunk", content=text_block(obj.content)
            )
        elif isinstance(obj, ReasoningDelta):
            chunk = AgentThoughtChunk(
                session_update="agent_thought_chunk", content=text_block(obj.reasoning)
            )
        else:
            chunk = UserMessageChunk(
                session_update="user_message_chunk", content=text_block(obj.message)
            )
        update = chunk.model_dump(mode="json", by_alias=True, exclude_none=True)
    else:
        return chat_notification(session_id, part.model_dump(mode="json"))

    onyx = {"placement": part.placement.model_dump()}
    if tool is not None:
        if tool.raw_output is None:
            onyx["packet"] = obj.model_dump(mode="json")
        else:
            update["rawOutput"] = obj.model_dump(mode="json")
    elif isinstance(obj, UserMessagePacket):
        onyx["userMessage"] = obj.model_dump(mode="json", include={"id", "mentions"})
    update["_meta"] = {"onyx": onyx}
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionId": session_id, "update": update},
    }


def acp_line(
    session_id: str | None,
    part: AnswerStreamPart | StreamCursor,
    *,
    retain: bool = False,
) -> str:
    """Encode once when publishing to both replay storage and the live reader."""
    if (
        isinstance(part, Packet)
        and (cached := part.published_acp_line(session_id)) is not None
    ):
        return cached
    line = get_json_line(acp_message(session_id, part))
    if retain and isinstance(part, Packet):
        part.retain_acp_line(session_id, line)
    return line


def resume_block(
    block: str, *, cached_acp: bool, requested_acp: bool, session_id: str
) -> str:
    """Replay a whole cache chunk at its original cursor boundary."""
    if cached_acp == requested_acp:
        return block
    lines: list[str] = []
    for line in block.splitlines():
        item = json.loads(line)
        if requested_acp:
            # Older writers retained only display packets. Preserve their data
            # without manufacturing tool IDs or outcomes from layout.
            if item.get("obj", {}).get("type") in (
                "message_delta",
                "reasoning_delta",
                "user_message",
            ):
                result = acp_message(session_id, Packet.model_validate(item))
            else:
                result = chat_notification(session_id, item)
        elif item["method"] == "session/update":
            update = item["params"]["update"]
            meta = update["_meta"]["onyx"]
            obj = update.get("rawOutput") or meta.get("packet")
            if obj is None:
                text = update["content"]["text"]
                if update["sessionUpdate"] == "user_message_chunk":
                    obj = {
                        "type": "user_message",
                        "message": text,
                        **meta["userMessage"],
                    }
                elif update["sessionUpdate"] == "agent_thought_chunk":
                    obj = {"type": "reasoning_delta", "reasoning": text}
                else:
                    obj = {"type": "message_delta", "content": text}
            result = {"placement": meta["placement"], "obj": obj}
        else:
            result = item["params"]["packet"]
        lines.append(get_json_line(result))
    return "".join(lines)
