import json
import re
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.types import Receive, Scope, Send

from tests.integration.mock_services.mock_llm_server.models import Step, ToolCall
from tests.integration.mock_services.mock_llm_server.registry import ScriptRegistry

_COMPLETION_ID = "chatcmpl-mock"
_WORD_RE = re.compile(r"\S+\s*|\s+")
_ARGUMENT_FRAGMENTS = 3


def _usage(body: dict[str, Any], step: Step) -> dict[str, int]:
    prompt_tokens = max(1, len(json.dumps(body.get("messages") or [])) // 4)
    completion_chars = len(step.text or "") + len(step.reasoning or "")
    completion_chars += sum(len(call.arguments_json()) for call in step.tool_calls)
    completion_tokens = max(1, completion_chars // 4)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _chunk(
    model: str,
    delta: dict[str, Any] | None,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
) -> str:
    body: dict[str, Any] = {
        "id": _COMPLETION_ID,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": (
            []
            if delta is None
            else [{"index": 0, "delta": delta, "finish_reason": finish_reason}]
        ),
    }
    if usage is not None:
        body["usage"] = usage
    return f"data: {json.dumps(body)}\n\n"


def _fragments(text: str, count: int) -> list[str]:
    if not text:
        return [""]
    size = max(1, -(-len(text) // count))
    return [text[i : i + size] for i in range(0, len(text), size)]


def _tool_call_chunks(model: str, tool_calls: list[ToolCall]) -> list[str]:
    chunks = [
        _chunk(
            model,
            {
                "tool_calls": [
                    {
                        "index": index,
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": ""},
                    }
                ]
            },
        )
        for index, call in enumerate(tool_calls)
    ]
    # Interleave argument fragments across calls, as parallel calls stream.
    fragments = [
        _fragments(call.arguments_json(), _ARGUMENT_FRAGMENTS) for call in tool_calls
    ]
    for position in range(max((len(f) for f in fragments), default=0)):
        for index, call_fragments in enumerate(fragments):
            if position < len(call_fragments) and call_fragments[position]:
                chunks.append(
                    _chunk(
                        model,
                        {
                            "tool_calls": [
                                {
                                    "index": index,
                                    "function": {"arguments": call_fragments[position]},
                                }
                            ]
                        },
                    )
                )
    return chunks


def sse_chunks(
    step: Step, model: str, include_usage: bool, body: dict[str, Any]
) -> list[str]:
    chunks = [_chunk(model, {"role": "assistant", "content": ""})]
    chunks.extend(
        _chunk(model, {"reasoning_content": piece})
        for piece in _WORD_RE.findall(step.reasoning or "")
    )
    chunks.extend(
        _chunk(model, {"content": piece}) for piece in _WORD_RE.findall(step.text or "")
    )
    chunks.extend(_tool_call_chunks(model, step.tool_calls))
    chunks.append(_chunk(model, {}, finish_reason=step.resolved_finish_reason()))
    if include_usage:
        chunks.append(_chunk(model, None, usage=_usage(body, step)))
    chunks.append("data: [DONE]\n\n")
    return chunks


def completion_body(step: Step, model: str, body: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": step.text}
    if step.reasoning:
        message["reasoning_content"] = step.reasoning
    if step.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments_json()},
            }
            for call in step.tool_calls
        ]
    return {
        "id": _COMPLETION_ID,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": step.resolved_finish_reason(),
            }
        ],
        "usage": _usage(body, step),
    }


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error"}},
        status_code=status_code,
    )


async def _iterate(chunks: list[str]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk


class _DisconnectResponse(Response):
    """Sends the stream headers, then returns without a body, so uvicorn closes
    the connection before the first chunk."""

    async def __call__(
        self,
        scope: Scope,  # noqa: ARG002
        receive: Receive,  # noqa: ARG002
        send: Send,
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )


def create_app(registry: ScriptRegistry) -> FastAPI:
    app = FastAPI(title="mock-llm-server")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/scripts/{script_id}/v1/chat/completions")
    async def chat_completions(script_id: str, request: Request) -> Response:
        body: dict[str, Any] = await request.json()
        result = registry.serve(script_id, body)
        if result.client_error is not None or result.step is None:
            return _error(result.client_error or "mock_llm_server: no step", 400)

        step = result.step
        model = str(body.get("model", ""))
        stream = bool(body.get("stream"))
        if step.disconnect:
            if stream:
                return _DisconnectResponse()
            return _error("mock_llm_server: scripted disconnect", 500)
        if stream:
            include_usage = bool(
                (body.get("stream_options") or {}).get("include_usage")
            )
            return StreamingResponse(
                _iterate(sse_chunks(step, model, include_usage, body)),
                media_type="text/event-stream",
            )
        return JSONResponse(completion_body(step, model, body))

    return app


class MockLLMServerThread:
    """Runs the app with uvicorn in a daemon thread."""

    def __init__(
        self,
        registry: ScriptRegistry,
        port: int,
        host: str = "127.0.0.1",
        startup_timeout_s: float = 30.0,
    ) -> None:
        self.registry = registry
        self.host = host
        self.port = port
        self._startup_timeout_s = startup_timeout_s
        self._server = uvicorn.Server(
            uvicorn.Config(
                create_app(registry),
                host=host,
                port=port,
                log_level="warning",
                lifespan="off",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def api_base(self, script_id: str) -> str:
        return f"{self.base_url}/scripts/{script_id}/v1"

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + self._startup_timeout_s
        while not self._server.started:
            if not self._thread.is_alive():
                raise RuntimeError("mock LLM server exited during startup")
            if time.monotonic() > deadline:
                raise TimeoutError("mock LLM server did not start in time")
            time.sleep(0.05)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
