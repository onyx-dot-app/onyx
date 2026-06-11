"""Mock OpenAI-compatible LLM server for Onyx load testing.

The whole point: drive unlimited LLM call volume at zero cost with
deterministic timing, so load tests measure Onyx's application code and
infrastructure — never answer quality or a real provider's latency.

Register in Onyx as an `openai_compatible` provider with this server's URL as
`api_base`; Onyx/litellm then sends plain /v1/chat/completions requests with
the model name passed through verbatim.

Timing knobs are encoded in the model name (litellm passes it through):

    mock-model                      — env-var defaults
    mock-ttft500-itl20-len400       — 500ms to first token, 20ms between
                                      tokens, 400 tokens of filler answer

Tool-call behavior (exercises the real tool-execution path): when the request
offers tools and MOCK_FORCE_TOOL_CALL=true, the first call of a turn (no
tool-role message yet) responds with a tool call for the first offered tool;
the follow-up call (tool result present) streams the final answer.

Run locally:  uvicorn mock_llm.app:app --port 8001
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

app = FastAPI()

DEFAULT_TTFT_MS = int(os.environ.get("MOCK_TTFT_MS", "300"))
DEFAULT_ITL_MS = int(os.environ.get("MOCK_ITL_MS", "15"))
DEFAULT_LEN_TOKENS = int(os.environ.get("MOCK_LEN_TOKENS", "150"))
FORCE_TOOL_CALL = os.environ.get("MOCK_FORCE_TOOL_CALL", "").lower() == "true"

_KNOB_RE = re.compile(r"-(ttft|itl|len)(\d+)")

_FILLER_WORDS = (
    "This is deterministic mock answer content used only for load testing "
    "the Onyx application and infrastructure under controlled conditions. "
).split()


def _parse_knobs(model: str) -> tuple[float, float, int]:
    ttft_ms, itl_ms, n_tokens = DEFAULT_TTFT_MS, DEFAULT_ITL_MS, DEFAULT_LEN_TOKENS
    for name, value in _KNOB_RE.findall(model):
        if name == "ttft":
            ttft_ms = int(value)
        elif name == "itl":
            itl_ms = int(value)
        elif name == "len":
            n_tokens = int(value)
    return ttft_ms / 1000.0, itl_ms / 1000.0, n_tokens


def _chunk(
    model: str, completion_id: str, delta: dict[str, Any], finish: str | None
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/v1/models")
def list_models() -> JSONResponse:
    return JSONResponse(
        {
            "object": "list",
            "data": [{"id": "mock-model", "object": "model", "owned_by": "loadtest"}],
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    body = await request.json()
    model: str = body.get("model", "mock-model")
    stream: bool = body.get("stream", False)
    messages: list[dict[str, Any]] = body.get("messages", [])
    tools: list[dict[str, Any]] | None = body.get("tools")
    ttft_s, itl_s, n_tokens = _parse_knobs(model)
    completion_id = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"

    has_tool_result = any(m.get("role") == "tool" for m in messages)
    do_tool_call = bool(FORCE_TOOL_CALL and tools and not has_tool_result)

    answer = " ".join(_FILLER_WORDS[i % len(_FILLER_WORDS)] for i in range(n_tokens))

    if not stream:
        await asyncio.sleep(ttft_s + itl_s * n_tokens)
        message: dict[str, Any] = {"role": "assistant", "content": answer}
        finish = "stop"
        if do_tool_call:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [_tool_call(tools, messages)],
            }
            finish = "tool_calls"
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": n_tokens,
                    "total_tokens": 100 + n_tokens,
                },
            }
        )

    async def generate() -> Any:
        await asyncio.sleep(ttft_s)
        if do_tool_call:
            tool_call = _tool_call(tools, messages)
            yield _chunk(
                model,
                completion_id,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": tool_call["id"],
                            "type": "function",
                            "function": {
                                "name": tool_call["function"]["name"],
                                "arguments": "",
                            },
                        }
                    ],
                },
                None,
            )
            yield _chunk(
                model,
                completion_id,
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {
                                "arguments": tool_call["function"]["arguments"]
                            },
                        }
                    ]
                },
                None,
            )
            yield _chunk(model, completion_id, {}, "tool_calls")
        else:
            yield _chunk(
                model, completion_id, {"role": "assistant", "content": ""}, None
            )
            for i in range(n_tokens):
                word = _FILLER_WORDS[i % len(_FILLER_WORDS)]
                yield _chunk(model, completion_id, {"content": word + " "}, None)
                if itl_s > 0:
                    await asyncio.sleep(itl_s)
            yield _chunk(model, completion_id, {}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def _tool_call(
    tools: list[dict[str, Any]] | None, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    tool_name = "run_search"
    if tools:
        tool_name = tools[0].get("function", {}).get("name", tool_name)
    last_user = next(
        (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
        "load test query",
    )
    if not isinstance(last_user, str):
        last_user = "load test query"
    return {
        "id": f"call_mock_{uuid.uuid4().hex[:10]}",
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": json.dumps({"query": last_user[:200]}),
        },
    }
