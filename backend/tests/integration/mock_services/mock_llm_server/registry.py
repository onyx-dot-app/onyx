import threading
from dataclasses import dataclass, field
from typing import Any

from tests.integration.mock_services.mock_llm_server.models import (
    Lane,
    RecordedMessage,
    RecordedRequest,
    Script,
    Step,
    ToolCall,
)
from tests.integration.mock_services.mock_llm_server.responders import (
    Builtin,
    find_builtin,
)

_VALID_BUILTINS = {b.value for b in Builtin}


@dataclass
class ServeResult:
    request: RecordedRequest | None
    step: Step | None
    # Sent to the client. Never quotes the prompt, and never names a request
    # parameter, since Onyx retries 400s whose message names one.
    client_error: str | None = None


@dataclass
class _ScriptState:
    script: Script
    cursors: dict[str, int] = field(default_factory=dict)
    requests: list[RecordedRequest] = field(default_factory=list)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _parse_message(raw: dict[str, Any]) -> RecordedMessage:
    tool_calls = [
        ToolCall(
            id=str(call.get("id", "")),
            name=str((call.get("function") or {}).get("name", "")),
            arguments=str((call.get("function") or {}).get("arguments") or ""),
        )
        for call in raw.get("tool_calls") or []
    ]
    return RecordedMessage(
        role=str(raw.get("role", "")),
        content=_content_text(raw.get("content")),
        tool_call_id=raw.get("tool_call_id"),
        tool_calls=tool_calls,
    )


def _tool_choice(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        function = raw.get("function") or {}
        return str(function.get("name")) if function.get("name") else None
    return None


def _response_format(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("type") == "json_schema":
        return str((raw.get("json_schema") or {}).get("name") or "json_schema")
    return str(raw.get("type")) if raw.get("type") else None


def parse_request(script_id: str, index: int, body: dict[str, Any]) -> RecordedRequest:
    stream_options = body.get("stream_options") or {}
    max_tokens = body.get("max_tokens", body.get("max_completion_tokens"))
    return RecordedRequest(
        index=index,
        script_id=script_id,
        model=str(body.get("model", "")),
        stream=bool(body.get("stream")),
        include_usage=bool(stream_options.get("include_usage")),
        messages=[_parse_message(m) for m in body.get("messages") or []],
        tools=[
            str((tool.get("function") or {}).get("name", ""))
            for tool in body.get("tools") or []
        ],
        tool_choice=_tool_choice(body.get("tool_choice")),
        response_format=_response_format(body.get("response_format")),
        max_tokens=int(max_tokens) if max_tokens is not None else None,
        raw_body=body,
    )


class ScriptRegistry:
    """In-memory scripts keyed by the id in the request path."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scripts: dict[str, _ScriptState] = {}

    def register(self, script_id: str, script: Script | None = None) -> None:
        script = script or Script()
        _validate_builtins(script.builtin_overrides.keys() | script.disabled_builtins)
        _validate_lane_names([lane.name for lane in script.lanes])
        with self._lock:
            if script_id in self._scripts:
                raise ValueError(f"script {script_id} is already registered")
            self._scripts[script_id] = _ScriptState(script=script.model_copy(deep=True))

    def remove(self, script_id: str) -> None:
        with self._lock:
            self._scripts.pop(script_id, None)

    def add_lane(self, script_id: str, lane: Lane) -> None:
        with self._lock:
            state = self._state(script_id)
            _validate_lane_names([ln.name for ln in state.script.lanes] + [lane.name])
            state.script.lanes.append(lane.model_copy(deep=True))

    def extend_lane(self, script_id: str, lane_name: str, steps: list[Step]) -> None:
        with self._lock:
            lane = self._lane(self._state(script_id), lane_name)
            lane.steps.extend(step.model_copy(deep=True) for step in steps)

    def set_builtin(self, script_id: str, name: str, text: str) -> None:
        _validate_builtins({name})
        with self._lock:
            self._state(script_id).script.builtin_overrides[name] = text

    def disable_builtin(self, script_id: str, name: str) -> None:
        _validate_builtins({name})
        with self._lock:
            self._state(script_id).script.disabled_builtins.add(name)

    def requests(self, script_id: str) -> list[RecordedRequest]:
        with self._lock:
            return [r.model_copy(deep=True) for r in self._state(script_id).requests]

    def pending_required_steps(self, script_id: str) -> list[str]:
        with self._lock:
            state = self._state(script_id)
            return [
                f"lane '{lane.name}' step {index}"
                for lane in state.script.lanes
                for index in range(state.cursors.get(lane.name, 0), len(lane.steps))
                if lane.steps[index].required
            ]

    def serve(self, script_id: str, body: dict[str, Any]) -> ServeResult:
        with self._lock:
            state = self._scripts.get(script_id)
            if state is None:
                return ServeResult(
                    request=None,
                    step=None,
                    client_error=f"mock_llm_server: unknown script {script_id}",
                )
            request = parse_request(script_id, len(state.requests), body)
            state.requests.append(request)
            return self._serve_locked(state, request)

    def _serve_locked(
        self, state: _ScriptState, request: RecordedRequest
    ) -> ServeResult:
        script = state.script
        responder = find_builtin(request, script.disabled_builtins)
        if responder is not None:
            request.builtin = responder.name.value
            text = script.builtin_overrides.get(
                responder.name.value, responder.respond(request)
            )
            return ServeResult(request=request, step=Step(text=text))

        candidates: list[tuple[Lane, int]] = []
        for lane in script.lanes:
            cursor = state.cursors.get(lane.name, 0)
            if cursor >= len(lane.steps):
                continue
            step = lane.steps[cursor]
            if not lane.match.matches(request):
                continue
            if step.match is not None and not step.match.matches(request):
                continue
            candidates.append((lane, cursor))

        if not candidates:
            request.error = "no pending step matched"
            return ServeResult(
                request=request,
                step=None,
                client_error=(
                    f"mock_llm_server: no scripted step matched request "
                    f"{request.index} of script {request.script_id}"
                ),
            )

        distinct = {lane.steps[cursor].response_key() for lane, cursor in candidates}
        if len(distinct) > 1:
            names = ", ".join(
                f"'{lane.name}' step {cursor}" for lane, cursor in candidates
            )
            request.error = f"ambiguous: more than one pending step matched ({names})"
            return ServeResult(
                request=request,
                step=None,
                client_error=(
                    f"mock_llm_server: request {request.index} of script "
                    f"{request.script_id} matched more than one scripted step"
                ),
            )

        lane, cursor = candidates[0]
        state.cursors[lane.name] = cursor + 1
        request.lane = lane.name
        request.step_index = cursor
        return ServeResult(request=request, step=lane.steps[cursor])

    def _state(self, script_id: str) -> _ScriptState:
        state = self._scripts.get(script_id)
        if state is None:
            raise KeyError(f"script {script_id} is not registered")
        return state

    @staticmethod
    def _lane(state: _ScriptState, lane_name: str) -> Lane:
        for lane in state.script.lanes:
            if lane.name == lane_name:
                return lane
        raise KeyError(f"lane '{lane_name}' is not defined")


def _validate_builtins(names: set[str]) -> None:
    unknown = names - _VALID_BUILTINS
    if unknown:
        raise ValueError(f"unknown built-in responders: {sorted(unknown)}")


def _validate_lane_names(names: list[str]) -> None:
    if len(names) != len(set(names)):
        raise ValueError(f"lane names must be unique: {names}")
