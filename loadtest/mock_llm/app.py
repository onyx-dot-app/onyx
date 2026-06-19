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
    mock-tools3                     — call up to 3 retrieval tools in parallel
                                      on the AUTO cycle (multi-tool turn);
                                      capped by how many the persona offers
    mock-agents2                    — spawn 2 parallel research agents per
                                      deep-research orchestrator cycle
    mock-maxctx16000                — reject prompts over ~16k estimated tokens
                                      with a context-window error (mimics a
                                      provider; for long-thread overflow tests)

Knob combinations can imitate provider latency profiles (see README:
"Provider profiles") — e.g. a slow reasoning model is just
`mock-ttft8000-itl40-len600`.

Branching follows the contract of Onyx's LLM loops (chat llm_loop.py and
deep_research/dr_loop.py):

- tool_choice NONE / no tools        → stream plain filler text ("stop").
  Covers: final answers, DR plan / intermediate / final reports, and
  secondary invoke() flows (query rephrase, doc selection, ...).
- tool_choice forced to one function → call exactly that tool.
- tool_choice REQUIRED               → must emit a tool call. Priority:
  `research_agent` if not yet called in this history (DR orchestrator),
  else a retrieval tool if not yet called (DR research-agent loop),
  else `generate_report`, else the first offered tool.
- tool_choice AUTO                   → `generate_plan` if offered (DR
  clarification phase — always taken so a load-test DR turn never ends in a
  clarification question); else, with the `-tools<N>` knob and no tool result
  yet, up to N offered retrieval tools in parallel (normal chat-with-search,
  or a multi-tool turn for N>1); else plain text.

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
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Response
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

from mock_llm.models import AssistantMessage
from mock_llm.models import ChatCompletionChunk
from mock_llm.models import ChatCompletionRequest
from mock_llm.models import ChatCompletionResponse
from mock_llm.models import ChatMessage
from mock_llm.models import Choice
from mock_llm.models import ChunkChoice
from mock_llm.models import ChunkDelta
from mock_llm.models import StreamToolCall
from mock_llm.models import StreamToolCallFunction
from mock_llm.models import ToolCall
from mock_llm.models import ToolCallFunction
from mock_llm.models import ToolDefinition
from mock_llm.models import Usage

app = FastAPI()

DEFAULT_TTFT_MS = int(os.environ.get("MOCK_TTFT_MS", "300"))
DEFAULT_ITL_MS = int(os.environ.get("MOCK_ITL_MS", "15"))
DEFAULT_LEN_TOKENS = int(os.environ.get("MOCK_LEN_TOKENS", "150"))

_KNOB_RE = re.compile(r"-(ttft|itl|len|tools|agents|maxctx)(\d+)")

_FILLER_WORDS = (
    "This is deterministic mock answer content used only for load testing "
    "the Onyx application and infrastructure under controlled conditions. "
).split()

# Tool names from Onyx's chat / deep-research loops (see module docstring).
_RETRIEVAL_TOOLS = ("internal_search", "web_search", "open_url")
_RESEARCH_AGENT = "research_agent"
_GENERATE_REPORT = "generate_report"
_GENERATE_PLAN = "generate_plan"


class Knobs:
    def __init__(self, model: str) -> None:
        self.ttft_s: float = DEFAULT_TTFT_MS / 1000.0
        self.itl_s: float = DEFAULT_ITL_MS / 1000.0
        self.n_tokens: int = DEFAULT_LEN_TOKENS
        # Retrieval tools to call in parallel on an AUTO cycle (0=none,
        # 1=mock-tools1, 2+=multi-tool); capped by tools the persona offers.
        self.n_auto_tools: int = 0
        self.n_agents: int = 1
        # >0 makes the mock reject requests whose estimated prompt tokens exceed
        # this, mimicking a provider context-window error (mock-maxctx16000).
        self.max_ctx_tokens: int = 0
        for name, value in _KNOB_RE.findall(model):
            if name == "ttft":
                self.ttft_s = int(value) / 1000.0
            elif name == "itl":
                self.itl_s = int(value) / 1000.0
            elif name == "len":
                self.n_tokens = int(value)
            elif name == "tools":
                self.n_auto_tools = int(value)
            elif name == "agents":
                self.n_agents = max(1, int(value))
            elif name == "maxctx":
                self.max_ctx_tokens = int(value)


def _assistant_called(messages: list[ChatMessage], names: tuple[str, ...]) -> bool:
    """True if any assistant message in the history already called one of
    `names` — the stateless signal for which phase of a loop we're in."""
    for message in messages:
        if message.role != "assistant":
            continue
        for tool_call in message.tool_calls or []:
            if tool_call.function.name in names:
                return True
    return False


def _content_text(content: str | list[Any] | None) -> str | None:
    """Extract text from message content, which is either a plain string or
    a list of multimodal content parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return str(part.get("text", ""))
    return None


def _last_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role != "user":
            continue
        text = _content_text(message.content)
        if text is not None:
            return text
    return "load test query"


def _last_user_snippet(messages: list[ChatMessage]) -> str:
    return _last_user_text(messages)[:200]


# Stable phrases from Onyx's secondary-flow prompts whose LLM output feeds
# back into the pipeline (backend/onyx/prompts/search_prompts.py — both the
# semantic and keyword query-rephrase system prompts share this prefix). For
# these calls the mock must echo the real question's terms, not filler, or
# retrieval searches for nonsense and returns nothing.
_ECHO_PROMPT_MARKERS = ("reformulates the last user message",)


def _is_echo_flow(messages: list[ChatMessage]) -> bool:
    for message in messages:
        if message.role != "system" or not isinstance(message.content, str):
            continue
        if any(marker in message.content for marker in _ECHO_PROMPT_MARKERS):
            return True
    return False


def _echo_answer(messages: list[ChatMessage]) -> str:
    """Prompt templates put the actual question at the end of the user
    message, so echo the tail."""
    return _last_user_text(messages)[-300:]


def _synthesize_arguments(tool: ToolDefinition, snippet: str) -> str:
    """Fill a tool's required params from its JSON schema: strings get the
    user-message snippet, string-arrays get a one-element list."""
    params = tool.function.parameters or {}
    properties = params.get("properties", {}) or {}
    required = params.get("required", list(properties.keys())) or []
    args: dict[str, object] = {}
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


def _pick_tool(request: ChatCompletionRequest, knobs: Knobs) -> list[ToolCall]:
    """Decide which tool call(s) to emit; empty list means stream text."""
    tools = request.tools or []
    by_name = {t.function.name: t for t in tools}
    messages = request.messages
    snippet = _last_user_snippet(messages)
    has_tool_result = any(m.role == "tool" for m in messages)

    def make(tool: ToolDefinition, task: str | None = None) -> ToolCall:
        return ToolCall(
            id=f"call_mock_{uuid.uuid4().hex[:10]}",
            function=ToolCallFunction(
                name=tool.function.name,
                arguments=_synthesize_arguments(tool, task or snippet),
            ),
        )

    # Forced specific function: {"type": "function", "function": {"name": ...}}
    if isinstance(request.tool_choice, dict):
        forced = request.tool_choice.get("function", {}).get("name")
        if not forced or forced not in by_name:
            # Mirror OpenAI: 400 on a forced function that isn't offered.
            # Failing loudly matters here — silent fallback would mask the
            # exact contract violations this mock exists to surface.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid 'tool_choice': function {forced!r} is not in "
                    f"'tools': {sorted(by_name)}"
                ),
            )
        return [make(by_name[forced])]

    choice = request.tool_choice if isinstance(request.tool_choice, str) else None
    if choice is None:
        choice = "auto" if tools else "none"

    if choice == "none" or not tools:
        return []

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
                ]
            if _GENERATE_REPORT in by_name:
                return [make(by_name[_GENERATE_REPORT])]
        # DR research-agent loop: search once, then ask for the report.
        retrieval_tool = next((n for n in _RETRIEVAL_TOOLS if n in by_name), None)
        if retrieval_tool and not _assistant_called(messages, _RETRIEVAL_TOOLS):
            return [make(by_name[retrieval_tool])]
        if _GENERATE_REPORT in by_name:
            return [make(by_name[_GENERATE_REPORT])]
        return [make(tools[0])]

    # choice == "auto"
    # DR clarification: always proceed to the plan, never ask to clarify.
    if _GENERATE_PLAN in by_name:
        return [make(by_name[_GENERATE_PLAN])]
    if knobs.n_auto_tools > 0 and not has_tool_result:
        # Up to n_auto_tools retrieval tools in parallel; else the first tool.
        retrieval = [by_name[n] for n in _RETRIEVAL_TOOLS if n in by_name]
        chosen = retrieval[: knobs.n_auto_tools]
        if not chosen and tools:
            chosen = [tools[0]]
        if chosen:
            return [make(t) for t in chosen]
    return []


def _sse(chunk: ChatCompletionChunk) -> str:
    # Match OpenAI's wire format: unset fields are omitted inside delta (and
    # its tool_calls entries), but finish_reason is always present (null).
    data = chunk.model_dump()
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


def _estimate_prompt_tokens(messages: list[ChatMessage]) -> int:
    """Rough token estimate of the whole prompt (~4 chars/token), used only to
    decide whether to simulate a context-window overflow."""
    chars = 0
    for message in messages:
        text = _content_text(message.content) or ""
        chars += len(text) + 4  # small per-message role/format overhead
    return chars // 4


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


@app.get("/v1/models")
def list_models() -> JSONResponse:
    return JSONResponse(
        {
            "object": "list",
            "data": [{"id": "mock-model", "object": "model", "owned_by": "loadtest"}],
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest) -> Response:
    knobs = Knobs(request.model)
    completion_id = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"

    # Simulate a provider context-window overflow on long prompts (mock-maxctx).
    if knobs.max_ctx_tokens:
        prompt_tokens = _estimate_prompt_tokens(request.messages)
        if prompt_tokens > knobs.max_ctx_tokens:
            return _context_window_error(knobs.max_ctx_tokens, prompt_tokens)

    tool_calls = _pick_tool(request, knobs)
    emit_tools = bool(tool_calls)

    n_tokens = knobs.n_tokens
    if request.effective_max_tokens is not None:
        n_tokens = min(n_tokens, max(1, request.effective_max_tokens))
    if _is_echo_flow(request.messages):
        # NOTE: invoke() also streams at the litellm layer, so echo-flow
        # detection must come from the prompt, not the stream flag.
        answer = _echo_answer(request.messages)
        n_tokens = len(answer.split())
    else:
        answer = " ".join(
            _FILLER_WORDS[i % len(_FILLER_WORDS)] for i in range(n_tokens)
        )

    if not request.stream:
        await asyncio.sleep(
            knobs.ttft_s + (0 if emit_tools else knobs.itl_s * n_tokens)
        )
        if emit_tools:
            message = AssistantMessage(content=None, tool_calls=tool_calls)
            finish = "tool_calls"
        else:
            message = AssistantMessage(content=answer)
            finish = "stop"
        completion_tokens = 20 if emit_tools else n_tokens
        response = ChatCompletionResponse(
            id=completion_id,
            created=int(time.time()),
            model=request.model,
            choices=[Choice(message=message, finish_reason=finish)],
            usage=Usage(
                prompt_tokens=100,
                completion_tokens=completion_tokens,
                total_tokens=100 + completion_tokens,
            ),
        )
        return JSONResponse(response.model_dump())

    async def generate() -> AsyncGenerator[str, None]:
        await asyncio.sleep(knobs.ttft_s)
        if emit_tools:
            # Header chunk: ids + names with empty arguments, then one
            # argument-delta chunk per call (OpenAI parallel format).
            yield _sse(
                _make_chunk(
                    request.model,
                    completion_id,
                    ChunkDelta(
                        role="assistant",
                        tool_calls=[
                            StreamToolCall(
                                index=i,
                                id=tc.id,
                                type="function",
                                function=StreamToolCallFunction(
                                    name=tc.function.name, arguments=""
                                ),
                            )
                            for i, tc in enumerate(tool_calls)
                        ],
                    ),
                    None,
                )
            )
            for i, tc in enumerate(tool_calls):
                yield _sse(
                    _make_chunk(
                        request.model,
                        completion_id,
                        ChunkDelta(
                            tool_calls=[
                                StreamToolCall(
                                    index=i,
                                    function=StreamToolCallFunction(
                                        arguments=tc.function.arguments
                                    ),
                                )
                            ]
                        ),
                        None,
                    )
                )
            yield _sse(
                _make_chunk(request.model, completion_id, ChunkDelta(), "tool_calls")
            )
        else:
            yield _sse(
                _make_chunk(
                    request.model,
                    completion_id,
                    ChunkDelta(role="assistant", content=""),
                    None,
                )
            )
            for word in answer.split():
                yield _sse(
                    _make_chunk(
                        request.model,
                        completion_id,
                        ChunkDelta(content=word + " "),
                        None,
                    )
                )
                if knobs.itl_s > 0:
                    await asyncio.sleep(knobs.itl_s)
            yield _sse(_make_chunk(request.model, completion_id, ChunkDelta(), "stop"))
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
