"""Shared OpenCode raw-event parser used by local and Kubernetes clients."""

import json
from collections.abc import Generator
from typing import Any

from onyx.server.features.build.sandbox.opencode.events import (
    OpenCodeAgentMessageChunk,
)
from onyx.server.features.build.sandbox.opencode.events import (
    OpenCodeAgentThoughtChunk,
)
from onyx.server.features.build.sandbox.opencode.events import OpenCodeError
from onyx.server.features.build.sandbox.opencode.events import OpenCodeEvent
from onyx.server.features.build.sandbox.opencode.events import OpenCodePromptResponse
from onyx.server.features.build.sandbox.opencode.events import (
    OpenCodeSessionEstablished,
)
from onyx.server.features.build.sandbox.opencode.events import OpenCodeTextContent
from onyx.server.features.build.sandbox.opencode.events import OpenCodeToolCallProgress
from onyx.server.features.build.sandbox.opencode.events import OpenCodeToolCallStart
from onyx.server.features.build.sandbox.opencode.events import timestamp_ms_to_iso


def _normalize_status(status: Any) -> str:
    if not isinstance(status, str):
        return "pending"
    normalized = status.strip().lower()
    alias_map = {
        "running": "in_progress",
        "in-progress": "in_progress",
        "done": "completed",
        "success": "completed",
        "error": "failed",
    }
    normalized = alias_map.get(normalized, normalized)
    if normalized in {"pending", "in_progress", "completed", "failed", "cancelled"}:
        return normalized
    return "pending"


def _map_tool_kind(tool_name: str, raw_input: dict[str, Any] | None) -> str:
    """Map OpenCode tool name into the UI's existing tool kind bucket."""
    lower_name = tool_name.lower()

    if lower_name in {"glob", "grep", "websearch"}:
        return "search"
    if lower_name in {"read"}:
        return "read"
    if lower_name in {"bash"}:
        return "execute"
    if lower_name in {"task"}:
        return "task"
    if lower_name in {"apply_patch", "edit", "write"}:
        return "edit"

    if raw_input:
        if isinstance(raw_input.get("command"), str):
            return "execute"
        if isinstance(raw_input.get("patchText"), str):
            return "edit"
        if raw_input.get("subagent_type") or raw_input.get("subagentType"):
            return "task"

    return "other"


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _build_tool_content(
    tool_name: str,
    raw_input: dict[str, Any] | None,
    raw_output: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Build tool content blocks used by frontend diff/read parsing logic."""
    if tool_name.lower() == "apply_patch":
        metadata = _as_dict((raw_output or {}).get("metadata"))
        files = metadata.get("files") if metadata else None
        if isinstance(files, list):
            blocks: list[dict[str, Any]] = []
            for file_entry in files:
                if not isinstance(file_entry, dict):
                    continue
                path = file_entry.get("relativePath") or file_entry.get("filePath")
                blocks.append(
                    {
                        "type": "diff",
                        "path": path,
                        "oldText": file_entry.get("before") or "",
                        "newText": file_entry.get("after") or "",
                    }
                )
            if blocks:
                return blocks

        if raw_input and isinstance(raw_input.get("path"), str):
            return [{"type": "diff", "path": raw_input["path"]}]

    if tool_name.lower() == "read" and raw_output:
        output_text = raw_output.get("output")
        if isinstance(output_text, str):
            return [
                {
                    "type": "content",
                    "content": {"type": "text", "text": output_text},
                }
            ]

    return None


def looks_like_session_not_found(error_text: str) -> bool:
    lower = error_text.lower()
    candidates = (
        "session not found",
        "unknown session",
        "invalid session",
        "session does not exist",
    )
    return any(token in lower for token in candidates)


class OpenCodeEventParser:
    """Stateful parser that converts raw OpenCode JSON lines into UI packets."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id
        self._emitted_session_id: str | None = None
        self.saw_prompt_response = False
        self._seen_tool_call_ids: set[str] = set()

    def parse_raw_event(
        self, raw_event: dict[str, Any]
    ) -> Generator[OpenCodeEvent, None, None]:
        timestamp = timestamp_ms_to_iso(raw_event.get("timestamp"))

        session_id = raw_event.get("sessionID") or raw_event.get("sessionId")
        if isinstance(session_id, str):
            if self.session_id != session_id:
                self.session_id = session_id
            if self._emitted_session_id != session_id:
                self._emitted_session_id = session_id
                yield OpenCodeSessionEstablished(
                    opencode_session_id=session_id,
                    timestamp=timestamp,
                )

        raw_type = raw_event.get("type")
        part = _as_dict(raw_event.get("part")) or {}

        if raw_type == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                yield OpenCodeAgentMessageChunk(
                    opencode_session_id=self.session_id,
                    content=OpenCodeTextContent(text=text),
                    timestamp=timestamp,
                )
            return

        if raw_type == "reasoning":
            text = part.get("text")
            if isinstance(text, str) and text:
                yield OpenCodeAgentThoughtChunk(
                    opencode_session_id=self.session_id,
                    content=OpenCodeTextContent(text=text),
                    timestamp=timestamp,
                )
            return

        if raw_type == "tool_use":
            call_id = part.get("callID")
            tool_name = part.get("tool")
            state = _as_dict(part.get("state")) or {}
            raw_input = _as_dict(state.get("input"))
            metadata = _as_dict(state.get("metadata")) or {}
            output = state.get("output")
            title = state.get("title")
            status = _normalize_status(state.get("status"))

            if not isinstance(call_id, str) or not isinstance(tool_name, str):
                return

            kind = _map_tool_kind(tool_name, raw_input)
            raw_output: dict[str, Any] = {
                "output": (
                    output
                    if isinstance(output, str)
                    else json.dumps(output, default=str)
                ),
                "metadata": metadata,
            }

            if tool_name.lower() == "read" and isinstance(output, str):
                raw_output["content"] = output

            if tool_name.lower() == "task":
                task_session_id = metadata.get("sessionId") or metadata.get("sessionID")
                if not isinstance(task_session_id, str):
                    task_session_id = metadata.get("session_id")
                if isinstance(task_session_id, str):
                    raw_output["sessionId"] = task_session_id

            content = _build_tool_content(tool_name, raw_input, raw_output)

            if call_id not in self._seen_tool_call_ids:
                self._seen_tool_call_ids.add(call_id)
                yield OpenCodeToolCallStart(
                    opencode_session_id=self.session_id,
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    kind=kind,
                    title=title if isinstance(title, str) else None,
                    content=content,
                    raw_input=raw_input,
                    raw_output=None,
                    status="pending",
                    timestamp=timestamp,
                )

            yield OpenCodeToolCallProgress(
                opencode_session_id=self.session_id,
                tool_call_id=call_id,
                tool_name=tool_name,
                kind=kind,
                title=title if isinstance(title, str) else None,
                content=content,
                raw_input=raw_input,
                raw_output=raw_output,
                status=status,
                timestamp=timestamp,
            )
            return

        if raw_type == "step_finish":
            reason = part.get("reason")
            if isinstance(reason, str) and reason.lower() != "tool-calls":
                self.saw_prompt_response = True
                yield OpenCodePromptResponse(
                    opencode_session_id=self.session_id,
                    stop_reason=reason,
                    timestamp=timestamp,
                )
            return

        if raw_type == "error":
            message = part.get("message")
            if isinstance(message, str):
                yield OpenCodeError(
                    opencode_session_id=self.session_id,
                    message=message,
                    code=part.get("code"),
                    data=_as_dict(part.get("data")),
                    timestamp=timestamp,
                )
