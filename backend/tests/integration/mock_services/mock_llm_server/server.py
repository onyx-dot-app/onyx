"""Scripted OpenAI-compatible chat-completions server for integration tests."""

import json
import os
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from tests.integration.mock_services.mock_llm_server.models import (
    Conversation,
    RecordedMessage,
    RecordedRequest,
    Reply,
    Script,
    ScriptState,
    ToolCall,
)

MAX_RECORDED_REQUESTS = 1000
_COMPLETION_ID = "chatcmpl-mock"
_FRAGMENTS = 3


@dataclass
class _Entry:
    script: Script
    cursors: dict[int, int] = field(default_factory=dict)
    requests: deque[RecordedRequest] = field(
        default_factory=lambda: deque(maxlen=MAX_RECORDED_REQUESTS)
    )


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


def _arguments(raw: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_message(raw: dict[str, Any]) -> RecordedMessage:
    return RecordedMessage(
        role=str(raw.get("role", "")),
        content=_content_text(raw.get("content")),
        tool_call_id=raw.get("tool_call_id"),
        tool_calls=[
            ToolCall(
                id=str(call.get("id", "")),
                name=str((call.get("function") or {}).get("name", "")),
                arguments=_arguments((call.get("function") or {}).get("arguments")),
            )
            for call in raw.get("tool_calls") or []
        ],
    )


def _parse_request(body: dict[str, Any]) -> RecordedRequest:
    tool_choice = body.get("tool_choice")
    return RecordedRequest(
        messages=[_parse_message(m) for m in body.get("messages") or []],
        tools=[
            str((tool.get("function") or {}).get("name", ""))
            for tool in body.get("tools") or []
        ],
        tool_choice=tool_choice if isinstance(tool_choice, str) else None,
        body=body,
    )


def _allows_tool_free(conversation: Conversation, reply: Reply) -> bool:
    return conversation.conditions.has_tools is False or (
        reply.conditions is not None and reply.conditions.has_tools is False
    )


def _response_key(reply: Reply) -> str:
    return reply.model_dump_json(include={"reasoning", "text", "tool_calls"})


def _serve(entry: _Entry, request: RecordedRequest) -> Reply | None:
    candidates: list[tuple[int, int, Reply]] = []
    for conversation_index, conversation in enumerate(entry.script.conversations):
        cursor = entry.cursors.get(conversation_index, 0)
        if cursor >= len(conversation.replies):
            continue
        reply = conversation.replies[cursor]
        if request.is_tool_free and not _allows_tool_free(conversation, reply):
            continue
        if not conversation.conditions.matches(request):
            continue
        if reply.conditions is not None and not reply.conditions.matches(request):
            continue
        candidates.append((conversation_index, cursor, reply))

    if len({_response_key(reply) for _, _, reply in candidates}) > 1:
        conversations = entry.script.conversations
        names = ", ".join(
            f"'{conversations[ci].name}' reply {i}" for ci, i, _ in candidates
        )
        request.error = f"ambiguous: {names}"
        return None
    if candidates:
        conversation_index, cursor, reply = candidates[0]
        entry.cursors[conversation_index] = cursor + 1
        request.conversation = entry.script.conversations[conversation_index].name
        request.reply_index = cursor
        return reply
    if entry.script.default_reply is not None:
        request.used_default_reply = True
        return entry.script.default_reply
    request.error = "no reply matched"
    return None


def _pending_required(entry: _Entry) -> list[str]:
    return [
        f"conversation '{conversation.name}' reply {index}"
        for conversation_index, conversation in enumerate(entry.script.conversations)
        for index, reply in enumerate(conversation.replies)
        if index >= entry.cursors.get(conversation_index, 0) and reply.required
    ]


def _fragments(text: str) -> list[str]:
    size = max(1, -(-len(text) // _FRAGMENTS))
    return [text[i : i + size] for i in range(0, len(text), size)]


def _usage(body: dict[str, Any], reply: Reply) -> dict[str, int]:
    prompt_tokens = max(1, len(json.dumps(body.get("messages") or [])) // 4)
    completion = (reply.text or "") + (reply.reasoning or "")
    completion += "".join(json.dumps(call.arguments) for call in reply.tool_calls)
    completion_tokens = max(1, len(completion) // 4)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _finish_reason(reply: Reply) -> str:
    return "tool_calls" if reply.tool_calls else "stop"


def _chunk(model: str, choices: list[dict[str, Any]], **extra: Any) -> str:
    body = {
        "id": _COMPLETION_ID,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
        **extra,
    }
    return f"data: {json.dumps(body)}\n\n"


def _delta(model: str, delta: dict[str, Any], finish: str | None = None) -> str:
    return _chunk(model, [{"index": 0, "delta": delta, "finish_reason": finish}])


def _sse(reply: Reply, body: dict[str, Any]) -> Iterator[str]:
    model = str(body.get("model", ""))
    yield _delta(model, {"role": "assistant", "content": ""})
    for piece in _fragments(reply.reasoning or ""):
        yield _delta(model, {"reasoning_content": piece})
    for piece in _fragments(reply.text or ""):
        yield _delta(model, {"content": piece})
    for index, call in enumerate(reply.tool_calls):
        function = {"name": call.name, "arguments": ""}
        opening = {"index": index, "id": call.id, "type": "function"}
        yield _delta(model, {"tool_calls": [{**opening, "function": function}]})
    # Argument fragments interleave across calls, as parallel calls stream.
    fragments = [_fragments(json.dumps(call.arguments)) for call in reply.tool_calls]
    for position in range(max((len(f) for f in fragments), default=0)):
        for index, call_fragments in enumerate(fragments):
            if position < len(call_fragments):
                function = {"arguments": call_fragments[position]}
                call_delta = {"index": index, "function": function}
                yield _delta(model, {"tool_calls": [call_delta]})
    yield _delta(model, {}, finish=_finish_reason(reply))
    if (body.get("stream_options") or {}).get("include_usage"):
        yield _chunk(model, [], usage=_usage(body, reply))
    yield "data: [DONE]\n\n"


def _completion(reply: Reply, body: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": reply.text,
        "reasoning_content": reply.reasoning,
    }
    if reply.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in reply.tool_calls
        ]
    return {
        "id": _COMPLETION_ID,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(body.get("model", "")),
        "choices": [
            {"index": 0, "message": message, "finish_reason": _finish_reason(reply)}
        ],
        "usage": _usage(body, reply),
    }


def _error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": {"message": message}}, status_code=status_code)


def create_app() -> FastAPI:
    # Every route is async, so all state access runs on the event loop thread.
    scripts: dict[str, _Entry] = {}
    app = FastAPI(title="mock-llm-server")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.put("/scripts/{script_id}")
    async def put_script(script_id: str, script: Script) -> Response:
        scripts[script_id] = _Entry(script=script)
        return Response(status_code=204)

    @app.post("/scripts/{script_id}/conversations")
    async def add_conversation(script_id: str, conversation: Conversation) -> Response:
        entry = scripts.get(script_id)
        if entry is None:
            return _error(f"unknown script {script_id}", 404)
        entry.script.conversations.append(conversation)
        return Response(status_code=204)

    @app.get("/scripts/{script_id}", response_model=None)
    async def get_script(script_id: str) -> ScriptState | JSONResponse:
        entry = scripts.get(script_id)
        if entry is None:
            return _error(f"unknown script {script_id}", 404)
        return ScriptState(
            requests=list(entry.requests), pending_required=_pending_required(entry)
        )

    @app.delete("/scripts/{script_id}")
    async def delete_script(script_id: str) -> Response:
        scripts.pop(script_id, None)
        return Response(status_code=204)

    @app.post("/scripts/{script_id}/v1/chat/completions")
    async def chat_completions(script_id: str, request: Request) -> Response:
        entry = scripts.get(script_id)
        if entry is None:
            return _error(f"mock_llm_server: unknown script {script_id}")
        body: dict[str, Any] = await request.json()
        recorded = _parse_request(body)
        entry.requests.append(recorded)
        reply = _serve(entry, recorded)
        # Onyx retries a 400 whose message names a request parameter, so the
        # message never quotes the prompt or names a parameter.
        if reply is None and recorded.error == "no reply matched":
            return _error("mock_llm_server: no scripted reply matched this request")
        if reply is None:
            return _error("mock_llm_server: more than one scripted reply matched")
        if body.get("stream"):
            return StreamingResponse(_sse(reply, body), media_type="text/event-stream")
        return JSONResponse(_completion(reply, body))

    return app


@contextmanager
def run_in_thread(
    host: str = "127.0.0.1", port: int = 0, startup_timeout_s: float = 30.0
) -> Iterator[str]:
    """Serve the app in a daemon thread and yield its base URL."""
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(), host=host, port=port, log_level="warning", lifespan="off"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + startup_timeout_s
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("mock LLM server exited during startup")
        if time.monotonic() > deadline:
            raise TimeoutError("mock LLM server did not start in time")
        time.sleep(0.05)
    bound_port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://{host}:{bound_port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.environ.get("MOCK_LLM_SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("MOCK_LLM_SERVER_PORT", "8010")),
    )


if __name__ == "__main__":
    main()
