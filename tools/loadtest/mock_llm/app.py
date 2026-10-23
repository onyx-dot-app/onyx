"""OpenAI-compatible HTTP endpoints for the load-test mock.

response_plan.py owns response content, tool decisions, usage, and timing.
This module delivers the same plan through plain JSON or streamed SSE.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from mock_llm.metrics import CHUNKS, COMPLETED, REQUESTS, TOKENS
from mock_llm.models import (
    AssistantMessage,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChunkChoice,
    ChunkDelta,
)
from mock_llm.response_plan import Knobs, prepare_response, schedule, usage_for

app = FastAPI()


def _sse(chunk: ChatCompletionChunk) -> str:
    # Match OpenAI's wire format: unset fields are omitted inside delta (and
    # its tool_calls entries), but finish_reason is always present (null).
    data = chunk.model_dump(exclude_none=True)
    for choice in data["choices"]:
        delta = {k: v for k, v in choice["delta"].items() if v is not None}
        if "tool_calls" in delta:
            delta["tool_calls"] = [
                {
                    k: (
                        {fk: fv for fk, fv in v.items() if fv is not None}
                        if k == "function"
                        else v
                    )
                    for k, v in tc.items()
                    if v is not None
                }
                for tc in delta["tool_calls"]
            ]
        choice["delta"] = delta
        choice.setdefault("finish_reason", None)
    return f"data: {json.dumps(data)}\n\n"


def _make_chunk(
    model: str, completion_id: str, delta: ChunkDelta, finish: str | None
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id=completion_id,
        created=int(time.time()),
        model=model,
        choices=[ChunkChoice(delta=delta, finish_reason=finish)],
    )


def _context_window_error(limit: int, used: int) -> JSONResponse:
    """OpenAI-shaped context-length error → litellm maps it to
    ContextWindowExceededError, mimicking what Vertex/Claude return."""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "message": (
                    f"This model's maximum context length is {limit} tokens. "
                    f"However, your messages resulted in {used} tokens. "
                    "Please reduce the length of the messages."
                ),
                "type": "invalid_request_error",
                "param": "messages",
                "code": "context_length_exceeded",
            }
        },
    )


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


@app.get("/v1/models")
def list_models() -> JSONResponse:
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "owned_by": "loadtest"}
                for name in (
                    "mock-profile-chat-v1",
                    "mock-profile-search-v1",
                    "mock-profile-research-v1-agents2",
                    "mock-profile-held-v1",
                    "mock-model",
                    "mock-tools1",
                )
            ],
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest) -> Response:
    try:
        knobs = Knobs(request.model)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if knobs.max_ctx_tokens:
        prompt_tokens = usage_for(request, "", "", []).prompt_tokens
        if prompt_tokens > knobs.max_ctx_tokens:
            return _context_window_error(knobs.max_ctx_tokens, prompt_tokens)
    if "-fault429" in request.model:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": "Injected mock rate limit",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
            headers={"Retry-After": "1"},
        )
    try:
        plan = prepare_response(request, knobs)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    REQUESTS.labels(
        plan.profile.kind if plan.profile else "stress",
        plan.profile.size if plan.profile else "fixed",
        plan.phase,
    ).inc()
    TOKENS.labels("input").observe(plan.usage.prompt_tokens)
    TOKENS.labels("output").observe(plan.usage.completion_tokens)
    CHUNKS.observe(len(plan.deltas))
    completion_id = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"
    started = time.monotonic()

    async def wait_until(offset: float) -> None:
        await asyncio.sleep(max(0, started + offset - time.monotonic()))

    if not request.stream:
        await wait_until(120 if "-faultstall" in request.model else plan.end_s)
        message = AssistantMessage(
            content=None if plan.calls else plan.answer,
            reasoning_content=plan.reasoning or None,
            tool_calls=plan.calls or None,
        )
        response = ChatCompletionResponse(
            id=completion_id,
            created=int(time.time()),
            model=request.model,
            choices=[Choice(message=message, finish_reason=plan.finish)],
            usage=plan.usage,
        )
        COMPLETED.labels("plain").inc()
        return JSONResponse(response.model_dump(exclude_none=True))

    async def generate() -> AsyncGenerator[str, None]:
        if "-faultstall" in request.model:
            yield _sse(
                _make_chunk(
                    request.model, completion_id, ChunkDelta(role="assistant"), None
                )
            )
            await wait_until(120)
        for event in schedule(plan.deltas, plan.first_s, plan.end_s):
            await wait_until(event.offset_s)
            yield _sse(_make_chunk(request.model, completion_id, event.delta, None))
        await wait_until(plan.end_s)
        yield _sse(_make_chunk(request.model, completion_id, ChunkDelta(), plan.finish))
        if request.stream_options and request.stream_options.include_usage:
            yield _sse(
                ChatCompletionChunk(
                    id=completion_id,
                    created=int(time.time()),
                    model=request.model,
                    choices=[],
                    usage=plan.usage,
                )
            )
        COMPLETED.labels("stream").inc()
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
