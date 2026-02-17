"""HTTP streaming client for OpenCode server event and prompt APIs."""

import json
import socket
import time
from collections.abc import Generator
from http.client import HTTPResponse
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.configs import OPENCODE_MESSAGE_TIMEOUT
from onyx.server.features.build.configs import SSE_KEEPALIVE_INTERVAL
from onyx.server.features.build.sandbox.opencode.events import OpenCodeError
from onyx.server.features.build.sandbox.opencode.events import OpenCodeEvent
from onyx.server.features.build.sandbox.opencode.events import OpenCodePromptResponse
from onyx.server.features.build.sandbox.opencode.events import OpenCodeSSEKeepalive
from onyx.server.features.build.sandbox.opencode.parser import (
    looks_like_session_not_found,
)
from onyx.server.features.build.sandbox.opencode.parser import OpenCodeEventParser
from onyx.server.features.build.sandbox.opencode.run_client import (
    OpenCodeSessionNotFoundError,
)


READ_TIMEOUT_SECONDS = 1.0


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _extract_timestamp_ms(value: dict[str, Any]) -> int | float | None:
    """Extract a millisecond timestamp from `time` metadata, if present."""
    time_obj = _as_dict(value.get("time")) or {}
    for key in ("end", "completed", "start", "created", "updated"):
        ts = time_obj.get(key)
        if isinstance(ts, (int, float)):
            return ts
    return None


def _extract_session_error_message(error_payload: dict[str, Any] | None) -> str:
    if not error_payload:
        return "OpenCode session failed"

    message = error_payload.get("message")
    if isinstance(message, str) and message:
        return message

    data = _as_dict(error_payload.get("data"))
    if data:
        nested = data.get("message")
        if isinstance(nested, str) and nested:
            return nested

    return json.dumps(error_payload, default=str)


def _build_raw_event_from_part(
    part: dict[str, Any],
    delta: str | None,
) -> dict[str, Any] | None:
    """Translate OpenCode SSE `message.part.updated` payload into run-style events."""
    part_type = part.get("type")
    session_id = part.get("sessionID")
    if not isinstance(part_type, str) or not isinstance(session_id, str):
        return None

    timestamp = _extract_timestamp_ms(part)

    if part_type == "text":
        text_value = delta if isinstance(delta, str) else part.get("text")
        if not isinstance(text_value, str) or not text_value:
            return None
        return {
            "type": "text",
            "sessionID": session_id,
            "timestamp": timestamp,
            "part": {"text": text_value},
        }

    if part_type == "reasoning":
        text_value = delta if isinstance(delta, str) else part.get("text")
        if not isinstance(text_value, str) or not text_value:
            return None
        return {
            "type": "reasoning",
            "sessionID": session_id,
            "timestamp": timestamp,
            "part": {"text": text_value},
        }

    if part_type == "tool":
        call_id = part.get("callID")
        tool_name = part.get("tool")
        state = _as_dict(part.get("state")) or {}
        if not isinstance(call_id, str) or not isinstance(tool_name, str):
            return None
        return {
            "type": "tool_use",
            "sessionID": session_id,
            "timestamp": timestamp,
            "part": {
                "callID": call_id,
                "tool": tool_name,
                "state": state,
            },
        }

    if part_type == "step-finish":
        reason = part.get("reason")
        if not isinstance(reason, str):
            reason = "completed"
        return {
            "type": "step_finish",
            "sessionID": session_id,
            "timestamp": timestamp,
            "part": {"reason": reason},
        }

    if part_type == "error":
        message = part.get("message")
        if not isinstance(message, str):
            return None
        return {
            "type": "error",
            "sessionID": session_id,
            "timestamp": timestamp,
            "part": {
                "message": message,
                "code": part.get("code"),
                "data": _as_dict(part.get("data")),
            },
        }

    return None


class OpenCodeHttpClient:
    """Executes OpenCode turns using `/event` SSE and `/prompt_async` HTTP APIs."""

    def __init__(
        self,
        server_url: str,
        session_id: str | None = None,
        cwd: str | None = None,
        timeout: float = OPENCODE_MESSAGE_TIMEOUT,
        keepalive_interval: float = SSE_KEEPALIVE_INTERVAL,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._cwd = cwd
        self._timeout = timeout
        self._keepalive_interval = keepalive_interval
        self._parser = OpenCodeEventParser(session_id=session_id)

    @property
    def session_id(self) -> str | None:
        return self._parser.session_id

    def _build_url(self, path: str) -> str:
        if self._cwd:
            query = urlencode({"directory": self._cwd})
            return f"{self._server_url}{path}?{query}"
        return f"{self._server_url}{path}"

    def _create_session_if_needed(self) -> None:
        if self._parser.session_id:
            return

        request = Request(
            self._build_url("/session"),
            data=b"{}",
            method="POST",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
        with urlopen(request, timeout=15.0) as response:
            body = response.read().decode("utf-8")

        payload = json.loads(body) if body else {}
        session_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("OpenCode /session response missing session id")

        self._parser.session_id = session_id

    def _open_event_stream(self) -> HTTPResponse:
        request = Request(
            self._build_url("/event"),
            method="GET",
            headers={"accept": "text/event-stream"},
        )
        return urlopen(request, timeout=READ_TIMEOUT_SECONDS)

    def _send_prompt_async(self, message: str) -> None:
        session_id = self._parser.session_id
        if not session_id:
            raise RuntimeError("OpenCode session id missing before prompt_async")

        payload = {"parts": [{"type": "text", "text": message}]}
        request = Request(
            self._build_url(f"/session/{session_id}/prompt_async"),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=15.0):
                return
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 and looks_like_session_not_found(body):
                raise OpenCodeSessionNotFoundError(body)
            if exc.code == 404:
                raise OpenCodeSessionNotFoundError(
                    body or f"Session {session_id} not found"
                )
            raise RuntimeError(
                f"OpenCode prompt_async failed ({exc.code}): {body[:500]}"
            )

    def send_message(self, message: str) -> Generator[OpenCodeEvent, None, None]:
        """Send one message through OpenCode HTTP APIs and stream normalized events."""
        packet_logger = get_packet_logger()
        packet_logger.log_raw(
            "OPENCODE-HTTP-START",
            {
                "server_url": self._server_url,
                "session_id": self._parser.session_id,
                "cwd": self._cwd,
            },
        )

        message_roles: dict[str, str] = {}
        message_parent_ids: dict[str, str] = {}
        user_message_ids_by_session: dict[str, str] = {}
        assistant_message_ids_by_session: dict[str, str] = {}
        saw_target_busy = False
        saw_target_idle = False
        status = "started"
        error_preview: str | None = None

        try:
            self._create_session_if_needed()
            primary_session_id = self._parser.session_id
            if not primary_session_id:
                raise RuntimeError(
                    "OpenCode session id missing after /session creation"
                )
            session_parsers: dict[str, OpenCodeEventParser] = {
                primary_session_id: self._parser
            }

            def _get_parser_for_session(session_id: str) -> OpenCodeEventParser:
                parser = session_parsers.get(session_id)
                if parser is not None:
                    return parser
                parser = OpenCodeEventParser(session_id=session_id)
                session_parsers[session_id] = parser
                return parser

            with self._open_event_stream() as stream:
                self._send_prompt_async(message)

                start_time = time.monotonic()
                last_event_time = start_time
                data_lines: list[str] = []

                while True:
                    elapsed = time.monotonic() - start_time
                    if elapsed > self._timeout:
                        status = "timeout"
                        yield OpenCodeError(
                            opencode_session_id=primary_session_id,
                            code=-1,
                            message=(
                                "Timeout waiting for OpenCode response "
                                f"after {self._timeout:.1f}s"
                            ),
                        )
                        return

                    try:
                        raw_line = stream.readline()
                    except (TimeoutError, socket.timeout):
                        raw_line = None
                    except OSError as exc:
                        if "timed out" in str(exc).lower():
                            raw_line = None
                        else:
                            raise

                    if raw_line is None:
                        if (
                            time.monotonic() - last_event_time
                        ) >= self._keepalive_interval:
                            yield OpenCodeSSEKeepalive()
                            last_event_time = time.monotonic()
                        continue

                    # Stream closed by server.
                    if raw_line == b"":
                        break

                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

                    if not line:
                        if not data_lines:
                            continue

                        payload_str = "\n".join(data_lines)
                        data_lines.clear()
                        try:
                            payload = json.loads(payload_str)
                        except json.JSONDecodeError:
                            packet_logger.log_raw(
                                "OPENCODE-HTTP-PARSE-ERROR",
                                {"line": payload_str[:500]},
                            )
                            continue

                        if not isinstance(payload, dict):
                            continue

                        payload_type = payload.get("type")
                        properties = _as_dict(payload.get("properties")) or {}

                        if payload_type == "session.status":
                            status_session_id = properties.get("sessionID")
                            if (
                                isinstance(status_session_id, str)
                                and status_session_id == primary_session_id
                            ):
                                status_obj = _as_dict(properties.get("status")) or {}
                                status_type = status_obj.get("type")
                                if status_type == "busy":
                                    saw_target_busy = True
                                elif status_type == "idle":
                                    saw_target_idle = True
                                    if saw_target_busy:
                                        if not self._parser.saw_prompt_response:
                                            yield OpenCodePromptResponse(
                                                opencode_session_id=primary_session_id,
                                                stop_reason="completed",
                                            )
                                        status = "completed"
                                        return
                            continue

                        if payload_type == "session.error":
                            status_session_id = properties.get("sessionID")
                            if (
                                isinstance(status_session_id, str)
                                and status_session_id == primary_session_id
                            ):
                                error_payload = _as_dict(properties.get("error"))
                                status = "failed"
                                yield OpenCodeError(
                                    opencode_session_id=primary_session_id,
                                    code=(
                                        error_payload.get("name")
                                        if error_payload
                                        else None
                                    ),
                                    message=_extract_session_error_message(
                                        error_payload
                                    ),
                                    data=error_payload,
                                )
                                return
                            continue

                        if payload_type == "message.updated":
                            info = _as_dict(properties.get("info")) or {}
                            info_session_id = info.get("sessionID")
                            if not isinstance(info_session_id, str):
                                continue

                            parser_for_session = _get_parser_for_session(
                                info_session_id
                            )
                            raw_info_event = {
                                "type": "noop",
                                "sessionID": info_session_id,
                                "timestamp": _extract_timestamp_ms(info),
                                "part": {},
                            }
                            for parsed_event in parser_for_session.parse_raw_event(
                                raw_info_event
                            ):
                                last_event_time = time.monotonic()
                                yield parsed_event

                            message_id = info.get("id")
                            role = info.get("role")
                            if isinstance(message_id, str) and isinstance(role, str):
                                message_roles[message_id] = role
                                parent_id = info.get("parentID")
                                if isinstance(parent_id, str):
                                    message_parent_ids[message_id] = parent_id

                                if (
                                    role == "user"
                                    and info_session_id
                                    not in user_message_ids_by_session
                                ):
                                    user_message_ids_by_session[info_session_id] = (
                                        message_id
                                    )
                                elif role == "assistant":
                                    user_message_id = user_message_ids_by_session.get(
                                        info_session_id
                                    )
                                    if (
                                        isinstance(parent_id, str)
                                        and parent_id == user_message_id
                                    ):
                                        assistant_message_ids_by_session[
                                            info_session_id
                                        ] = message_id
                            continue

                        if payload_type != "message.part.updated":
                            continue

                        part = _as_dict(properties.get("part")) or {}
                        part_session_id = part.get("sessionID")
                        if not isinstance(part_session_id, str):
                            continue

                        message_id = part.get("messageID")
                        if not isinstance(message_id, str):
                            continue

                        role = message_roles.get(message_id)
                        if role != "assistant":
                            continue

                        expected_assistant_id = assistant_message_ids_by_session.get(
                            part_session_id
                        )
                        if (
                            expected_assistant_id
                            and message_id != expected_assistant_id
                        ):
                            continue

                        if not expected_assistant_id:
                            user_message_id = user_message_ids_by_session.get(
                                part_session_id
                            )
                            parent_id = message_parent_ids.get(message_id)
                            if (
                                user_message_id
                                and isinstance(parent_id, str)
                                and parent_id != user_message_id
                            ):
                                continue
                            assistant_message_ids_by_session[part_session_id] = (
                                message_id
                            )

                        raw_part_event = _build_raw_event_from_part(
                            part=part,
                            delta=(
                                properties.get("delta")
                                if isinstance(properties.get("delta"), str)
                                else None
                            ),
                        )
                        if raw_part_event is None:
                            continue

                        parser_for_session = _get_parser_for_session(part_session_id)
                        for parsed_event in parser_for_session.parse_raw_event(
                            raw_part_event
                        ):
                            last_event_time = time.monotonic()
                            yield parsed_event
                            if (
                                isinstance(parsed_event, OpenCodePromptResponse)
                                and part_session_id == primary_session_id
                            ):
                                status = "completed"
                                return

                        continue

                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

                # Flush trailing buffered SSE data if stream closed mid-event.
                if data_lines:
                    payload_str = "\n".join(data_lines)
                    try:
                        payload = json.loads(payload_str)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        properties = _as_dict(payload.get("properties")) or {}
                        part = _as_dict(properties.get("part")) or {}
                        part_session_id = part.get("sessionID")
                        if not isinstance(part_session_id, str):
                            part_session_id = primary_session_id
                        raw_part_event = _build_raw_event_from_part(
                            part=part,
                            delta=(
                                properties.get("delta")
                                if isinstance(properties.get("delta"), str)
                                else None
                            ),
                        )
                        if raw_part_event:
                            parser_for_session = _get_parser_for_session(
                                part_session_id
                            )
                            for parsed_event in parser_for_session.parse_raw_event(
                                raw_part_event
                            ):
                                yield parsed_event
                                if (
                                    isinstance(parsed_event, OpenCodePromptResponse)
                                    and part_session_id == primary_session_id
                                ):
                                    status = "completed"
                                    return

            if not self._parser.saw_prompt_response:
                # Session may have completed without explicit step-finish event.
                stop_reason = "completed"
                if saw_target_idle and not saw_target_busy:
                    stop_reason = "idle"
                yield OpenCodePromptResponse(
                    opencode_session_id=primary_session_id,
                    stop_reason=stop_reason,
                )

            status = "completed"
        except OpenCodeSessionNotFoundError:
            status = "session_not_found"
            raise
        except Exception as exc:
            status = "failed"
            error_preview = str(exc)
            yield OpenCodeError(
                opencode_session_id=self._parser.session_id,
                message=error_preview,
            )
        finally:
            packet_logger.log_raw(
                "OPENCODE-HTTP-END",
                {
                    "server_url": self._server_url,
                    "session_id": self._parser.session_id,
                    "cwd": self._cwd,
                    "status": status,
                    "saw_prompt_response": self._parser.saw_prompt_response,
                    "error_preview": (error_preview[:500] if error_preview else None),
                },
            )
