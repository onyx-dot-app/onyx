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
    mock-tools1-ttft300             — emit a tool call on the first AUTO-
                                      tool-choice cycle (drives the search
                                      tool path in a normal chat turn)
    mock-agents2                    — spawn 2 parallel research agents per
                                      deep-research orchestrator cycle

Branching follows the contract of Onyx's LLM loops (chat llm_loop.py and
deep_research/dr_loop.py):

- tool_choice NONE / no tools        → stream plain filler text ("stop").
  Covers: final answers, DR plan / intermediate / final reports, and
  secondary invoke() flows (query rephrase, doc selection, ...).
- tool_choice forced to one function → call exactly that tool.
- tool_choice REQUIRED               → must emit a tool call. Priority:
  `research_agent` if not yet called in this history (DR orchestrator),
  else a search-ish tool if not yet called (DR research-agent loop),
  else `generate_report`, else the first offered tool.
- tool_choice AUTO                   → `generate_plan` if offered (DR
  clarification phase — always taken so a load-test DR turn never ends in a
  clarification question); else, with the `-tools1` knob and no tool result
  yet, the preferred search tool (normal chat-with-search); else plain text.

Tool-call arguments are synthesized from each tool's JSON schema (required
string props get a snippet of the last user message; arrays of strings get a
single-element list), so schema changes in Onyx degrade gracefully.

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

_KNOB_RE = re.compile(r"-(ttft|itl|len|tools|agents)(\d+)")

_FILLER_WORDS = (
    "This is deterministic mock answer content used only for load testing "
    "the Onyx application and infrastructure under controlled conditions. "
).split()

# Tool names from Onyx's chat / deep-research loops (see module docstring).
_SEARCHISH_TOOLS = ("internal_search", "web_search", "open_url")
_RESEARCH_AGENT = "research_agent"
_GENERATE_REPORT = "generate_report"
_GENERATE_PLAN = "generate_plan"


class Knobs:
    def __init__(self, model: str) -> None:
        self.ttft_s = DEFAULT_TTFT_MS / 1000.0
        self.itl_s = DEFAULT_ITL_MS / 1000.0
        self.n_tokens = DEFAULT_LEN_TOKENS
        self.tools_on_auto = False
        self.n_agents = 1
        for name, value in _KNOB_RE.findall(model):
            if name == "ttft":
                self.ttft_s = int(value) / 1000.0
            elif name == "itl":
                self.itl_s = int(value) / 1000.0
            elif name == "len":
                self.n_tokens = int(value)
            elif name == "tools":
                self.tools_on_auto = bool(int(value))
            elif name == "agents":
                self.n_agents = max(1, int(value))


def _tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    if not tools:
        return []
    return [t.get("function", {}).get("name", "") for t in tools]


def _assistant_called(messages: list[dict[str, Any]], names: tuple[str, ...]) -> bool:
    """True if any assistant message in the history already called one of
    `names` — the stateless signal for which phase of a loop we're in."""
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc.get("function", {}).get("name") in names:
                return True
    return False


def _last_user_snippet(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content[:200]
        if isinstance(content, list):  # multimodal content parts
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return str(part.get("text", ""))[:200]
    return "load test query"


def _synthesize_arguments(tool: dict[str, Any], snippet: str) -> str:
    """Fill a tool's required params from its JSON schema: strings get the
    user-message snippet, string-arrays get a one-element list."""
    params = tool.get("function", {}).get("parameters", {}) or {}
    properties = params.get("properties", {}) or {}
    required = params.get("required", list(properties.keys())) or []
    args: dict[str, Any] = {}
    for prop in required:
        schema = properties.get(prop, {})
        prop_type = schema.get("type")
        if prop_type == "array":
            args[prop] = [snippet]
        elif prop_type in (None, "string"):
            args[prop] = snippet
        elif prop_type in ("integer", "number"):
            args[prop] = 1
        elif prop_type == "boolean":
            args[prop] = True
        else:
            args[prop] = snippet
    return json.dumps(args)


def _pick_tool(
    tools: list[dict[str, Any]],
    tool_choice: Any,
    messages: list[dict[str, Any]],
    knobs: Knobs,
) -> tuple[list[dict[str, Any]], bool]:
    """Decide which tool call(s) to emit, if any.

    Returns (tool_calls, emit) where each tool_call is the full OpenAI
    non-streaming shape; emit=False means stream plain text instead.
    """
    names = _tool_names(tools)
    by_name = {n: t for n, t in zip(names, tools)}
    snippet = _last_user_snippet(messages)
    has_tool_result = any(m.get("role") == "tool" for m in messages)

    def make(tool: dict[str, Any], task: str | None = None) -> dict[str, Any]:
        arguments = _synthesize_arguments(tool, task or snippet)
        return {
            "id": f"call_mock_{uuid.uuid4().hex[:10]}",
            "type": "function",
            "function": {
                "name": tool.get("function", {}).get("name", ""),
                "arguments": arguments,
            },
        }

    # Forced specific function: {"type": "function", "function": {"name": ...}}
    if isinstance(tool_choice, dict):
        forced = tool_choice.get("function", {}).get("name")
        if forced and forced in by_name:
            return [make(by_name[forced])], True

    choice = tool_choice if isinstance(tool_choice, str) else None
    if choice is None:
        choice = "auto" if tools else "none"

    if choice == "none" or not tools:
        return [], False

    if choice == "required":
        # DR orchestrator: spawn agents once, then ask for the report.
        if _RESEARCH_AGENT in by_name:
            if not _assistant_called(messages, (_RESEARCH_AGENT,)):
                return [
                    make(
                        by_name[_RESEARCH_AGENT],
                        task=f"research aspect {i + 1}: {snippet}",
                    )
                    for i in range(knobs.n_agents)
                ], True
            if _GENERATE_REPORT in by_name:
                return [make(by_name[_GENERATE_REPORT])], True
        # DR research-agent loop: search once, then ask for the report.
        searchish = next((n for n in _SEARCHISH_TOOLS if n in by_name), None)
        if searchish and not _assistant_called(messages, _SEARCHISH_TOOLS):
            return [make(by_name[searchish])], True
        if _GENERATE_REPORT in by_name:
            return [make(by_name[_GENERATE_REPORT])], True
        return [make(tools[0])], True

    # choice == "auto"
    # DR clarification: always proceed to the plan, never ask to clarify.
    if _GENERATE_PLAN in by_name:
        return [make(by_name[_GENERATE_PLAN])], True
    if knobs.tools_on_auto and not has_tool_result:
        searchish = next((n for n in _SEARCHISH_TOOLS if n in by_name), None)
        target = by_name.get(searchish) if searchish else tools[0]
        if target is not None:
            return [make(target)], True
    return [], False


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
    tool_choice: Any = body.get("tool_choice")
    max_tokens: int | None = body.get("max_tokens") or body.get("max_completion_tokens")
    knobs = Knobs(model)
    completion_id = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"

    tool_calls, emit_tools = _pick_tool(tools or [], tool_choice, messages, knobs)

    n_tokens = knobs.n_tokens
    if max_tokens is not None:
        n_tokens = min(n_tokens, max(1, int(max_tokens)))
    answer = " ".join(_FILLER_WORDS[i % len(_FILLER_WORDS)] for i in range(n_tokens))

    if not stream:
        await asyncio.sleep(
            knobs.ttft_s + (0 if emit_tools else knobs.itl_s * n_tokens)
        )
        if emit_tools:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            }
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": answer}
            finish = "stop"
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": n_tokens if not emit_tools else 20,
                    "total_tokens": 100 + (n_tokens if not emit_tools else 20),
                },
            }
        )

    async def generate() -> Any:
        await asyncio.sleep(knobs.ttft_s)
        if emit_tools:
            # Header chunk: ids + names with empty arguments, then one
            # argument-delta chunk per call (OpenAI parallel format).
            yield _chunk(
                model,
                completion_id,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": i,
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": "",
                            },
                        }
                        for i, tc in enumerate(tool_calls)
                    ],
                },
                None,
            )
            for i, tc in enumerate(tool_calls):
                yield _chunk(
                    model,
                    completion_id,
                    {
                        "tool_calls": [
                            {
                                "index": i,
                                "function": {"arguments": tc["function"]["arguments"]},
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
                if knobs.itl_s > 0:
                    await asyncio.sleep(knobs.itl_s)
            yield _chunk(model, completion_id, {}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
