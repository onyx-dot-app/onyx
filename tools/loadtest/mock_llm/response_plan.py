"""Shared response content, usage, and deadlines for both transports."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

import tiktoken

from mock_llm import code_mode
from mock_llm.models import (
    ChatCompletionRequest,
    ChatMessage,
    ChunkDelta,
    StreamToolCall,
    StreamToolCallFunction,
    ToolCall,
    ToolCallFunction,
    ToolDefinition,
    Usage,
)
from mock_llm.profiles import (
    TurnProfile,
    current_question,
    profile_kind,
    question_after_label,
    turn_profile,
)
from mock_llm.search_workload import (
    helper_duration,
    helper_kind,
    keyword_query,
    search_helper_answer,
)


@cache
def encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    return len(encoding().encode_ordinary(text))


def truncate_tokens(text: str, maximum: int | None) -> tuple[str, bool]:
    tokens = encoding().encode_ordinary(text)
    if maximum is None or len(tokens) <= maximum:
        return text, False
    # A token boundary can bisect a Unicode codepoint. Drop that partial suffix.
    data = b"".join(encoding().decode_single_token_bytes(t) for t in tokens[:maximum])
    return data.decode("utf-8", errors="ignore"), True


def prompt_token_count(request: ChatCompletionRequest) -> int:
    """Tokenize the serialized prompt once for validation and simulated usage."""
    prompt = json.dumps(
        {
            "messages": [m.model_dump(exclude_none=True) for m in request.messages],
            "tools": [t.model_dump(exclude_none=True) for t in request.tools or []],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return token_count(prompt)


def usage_for(
    request: ChatCompletionRequest,
    answer: str,
    reasoning: str,
    calls: list[ToolCall],
    *,
    prompt_tokens: int | None = None,
) -> Usage:
    # Simulation convention, not provider billing.
    if prompt_tokens is None:
        prompt_tokens = prompt_token_count(request)
    generated = (
        answer
        + reasoning
        + "".join(c.function.name + c.function.arguments for c in calls)
    )
    completion_tokens = token_count(generated)
    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def fragments(text: str, width: int) -> list[str]:
    return [text[i : i + width] for i in range(0, len(text), width)]


def citation_ids(request: ChatCompletionRequest) -> list[int]:
    """Read only the tool-result envelope, never citation-like document prose.

    Direct search results are JSON. Code mode results are the printed lines of
    the mock's own programs (mock_llm/code_mode.py)."""
    ids: set[int] = set()
    last_user = _last_user_index(request.messages)
    for message in request.messages[last_user + 1 :]:
        if message.role != "tool" or not isinstance(message.content, str):
            continue
        try:
            payload = json.loads(message.content)
        except ValueError:
            ids |= code_mode.citation_ids(message.content)
            continue
        if not isinstance(payload, dict) or not isinstance(
            payload.get("results"), list
        ):
            continue
        for item in payload["results"]:
            if (
                isinstance(item, dict)
                and type(item.get("document")) is int
                and item["document"] > 0
            ):
                ids.add(item["document"])
    return sorted(ids)


@dataclass(frozen=True)
class ScheduledDelta:
    offset_s: float
    delta: ChunkDelta


def schedule(
    deltas: list[ChunkDelta], first_s: float, end_s: float
) -> list[ScheduledDelta]:
    """Absolute offsets avoid adding a scheduling delay for every fragment."""
    return [
        ScheduledDelta(first_s + (end_s - first_s) * i / max(1, len(deltas) - 1), delta)
        for i, delta in enumerate(deltas)
    ]


def limit_tool_calls(
    calls: list[ToolCall], budget: int | None
) -> tuple[list[ToolCall], bool]:
    if budget is None:
        return calls, False
    limited: list[ToolCall] = []
    for call in calls:
        name_tokens = token_count(call.function.name)
        if budget < name_tokens:
            return limited, True
        budget -= name_tokens
        arguments, truncated = truncate_tokens(call.function.arguments, budget)
        limited.append(
            call.model_copy(
                update={
                    "function": call.function.model_copy(
                        update={"arguments": arguments}
                    )
                }
            )
        )
        budget -= token_count(arguments)
        if truncated:
            return limited, True
    return limited, False


DEFAULT_TTFT_MS = int(os.environ.get("MOCK_TTFT_MS", "300"))
DEFAULT_ITL_MS = int(os.environ.get("MOCK_ITL_MS", "15"))
DEFAULT_LEN_TOKENS = int(os.environ.get("MOCK_LEN_TOKENS", "150"))

_KNOB_RE = re.compile(r"-(ttft|itl|len|tools|agents|maxctx|sections|class)(\d+)")

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
        self.selected_count: int | None = None
        self.classification: int | None = None
        # Retrieval tools to call in parallel on an AUTO cycle (0=none,
        # 1=mock-tools1, 2+=multi-tool); capped by tools the persona offers.
        self.n_auto_tools: int = 0
        self.n_agents: int = 1
        # >0 makes the mock reject requests whose estimated prompt tokens exceed
        # this, mimicking a provider context-window error (mock-maxctx16000).
        self.max_ctx_tokens: int = 0
        # Code mode only: one program runs every planned search round
        # (mock-profile-search-v1-codebatched) instead of one program per round.
        self.code_batched: bool = "-codebatched" in model
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
            elif name == "sections":
                self.selected_count = int(value)
            elif name == "class":
                if int(value) > 3:
                    raise ValueError("class must be between 0 and 3")
                self.classification = int(value)
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


def _last_user_index(messages: list[ChatMessage]) -> int:
    """Ignore Onyx's operational reminders when locating the user turn."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role != "user":
            continue
        text = (_content_text(message.content) or "").strip()
        # llm_step.py serializes USER_REMINDER messages with this wrapper.
        if text.startswith("<system-reminder>") and text.endswith("</system-reminder>"):
            continue
        return index
    return -1


def _last_user_text(messages: list[ChatMessage]) -> str:
    index = _last_user_index(messages)
    if index >= 0:
        text = _content_text(messages[index].content)
        if text is not None:
            return text
    return "load test query"


def _last_user_snippet(messages: list[ChatMessage]) -> str:
    """Text used to fill synthesized tool-call arguments (e.g. a search tool's
    query), so a search tool call searches for what the user asked.

    ONYX_MSG_CHARS pads a message with filler after the question, so cut at the
    first sentence end or newline instead of taking a fixed-width slice. The
    padding is identical for every user; searching it turns retrieval into a
    cache hit."""
    text = _last_user_text(messages)
    question = question_after_label(text)
    if question is None:
        head = text[:200].strip()
        end = min(
            (pos for pos in (head.find(mark) for mark in "?!.\n") if pos != -1),
            default=-1,
        )
        question = head[: end + 1].strip() if end != -1 else head
    return question[:200]


def _echo_answer(messages: list[ChatMessage]) -> str:
    """Rephrase templates put the question last, so an unlabelled prompt falls
    back to the tail."""
    text = _last_user_text(messages)
    return question_after_label(text) or text[-300:].strip()


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


def _rounds_called(turn: list[ChatMessage], name: str) -> int:
    """Assistant messages in the current turn that called `name`."""
    return sum(
        any(call.function.name == name for call in message.tool_calls or [])
        for message in turn
        if message.role == "assistant"
    )


def _round_queries(snippet: str, round_index: int, profile: TurnProfile) -> list[str]:
    """The seeded queries of one search round; the same in direct and code mode."""
    if round_index == 0:
        keywords = keyword_query(snippet)
        if keywords == snippet:
            keywords += " overview"
        queries = [snippet, keywords, snippet + " supporting details"][
            : profile.queries
        ]
    else:
        suffix = (" implementation", " limitations", " examples")[
            min(round_index - 1, 2)
        ]
        queries = [snippet + suffix]
    return list(dict.fromkeys(queries))


def _new_call(name: str, arguments: str) -> ToolCall:
    return ToolCall(
        id=f"call_mock_{uuid.uuid4().hex[:10]}",
        function=ToolCallFunction(name=name, arguments=arguments),
    )


def _search_profile_calls(
    messages: list[ChatMessage],
    by_name: dict[str, ToolDefinition],
    knobs: Knobs,
    profile: TurnProfile,
    snippet: str,
) -> list[ToolCall] | None:
    """The next step of the seeded search plan; None without a search tool."""
    turn = messages[_last_user_index(messages) + 1 :]
    if "internal_search" in by_name:
        completed_rounds = _rounds_called(turn, "internal_search")
        if completed_rounds >= profile.search_rounds:
            return []
        queries = _round_queries(snippet, completed_rounds, profile)
        return [_new_call("internal_search", json.dumps({"queries": queries}))]
    if code_mode.EXECUTE_CODE in by_name:
        return _code_mode_search(turn, by_name, knobs, profile, snippet)
    return None


def _code_mode_search(
    turn: list[ChatMessage],
    by_name: dict[str, ToolDefinition],
    knobs: Knobs,
    profile: TurnProfile,
    snippet: str,
) -> list[ToolCall]:
    """The search plan as execute_code programs: one per round, or one program
    that runs every round in parallel when `knobs.code_batched` is set."""
    cell = code_mode.running_cell(turn)
    if cell is not None and code_mode.WAIT_CODE in by_name:
        return [_new_call(code_mode.WAIT_CODE, json.dumps({"cell_id": cell}))]
    completed = _rounds_called(turn, code_mode.EXECUTE_CODE)
    if knobs.code_batched:
        if completed:
            return []
        rounds = range(profile.search_rounds)
    else:
        if completed >= profile.search_rounds:
            return []
        rounds = range(completed, completed + 1)
    program = code_mode.search_program(
        [("internal_search", _round_queries(snippet, i, profile)) for i in rounds]
    )
    return [_new_call(code_mode.EXECUTE_CODE, json.dumps({"code": program}))]


def _code_mode_retrieval(
    messages: list[ChatMessage],
    by_name: dict[str, ToolDefinition],
    limit: int,
    snippet: str,
) -> list[ToolCall]:
    """One program that calls up to `limit` query-taking retrieval functions in
    parallel. Empty without execute_code, after a program ran, or when the
    program offers no such function."""
    execute_code = by_name.get(code_mode.EXECUTE_CODE)
    if execute_code is None or _assistant_called(messages, (code_mode.EXECUTE_CODE,)):
        return []
    functions = code_mode.code_functions(execute_code)
    chosen = [name for name in code_mode.QUERY_FUNCTIONS if name in functions][
        : max(1, limit)
    ]
    if not chosen:
        return []
    program = code_mode.search_program([(name, [snippet]) for name in chosen])
    return [_new_call(code_mode.EXECUTE_CODE, json.dumps({"code": program}))]


def _pick_tool(
    request: ChatCompletionRequest,
    knobs: Knobs,
    profile: TurnProfile | None,
    question: str,
) -> list[ToolCall]:
    """Decide which tool call(s) to emit; empty list means stream text."""
    tools = request.tools or []
    by_name = {t.function.name: t for t in tools}
    messages = request.messages
    snippet = question if profile else _last_user_snippet(messages)
    has_tool_result = any(m.role == "tool" for m in messages)

    def make(tool: ToolDefinition, task: str | None = None) -> ToolCall:
        return _new_call(
            tool.function.name, _synthesize_arguments(tool, task or snippet)
        )

    # Forced specific function: {"type": "function", "function": {"name": ...}}
    if isinstance(request.tool_choice, dict):
        forced = request.tool_choice.get("function", {}).get("name")
        if not forced or forced not in by_name:
            # Mirror OpenAI: 400 on a forced function that isn't offered.
            # Failing loudly matters here — silent fallback would mask the
            # exact contract violations this mock exists to surface.
            raise ValueError(
                f"Invalid 'tool_choice': function {forced!r} is not in "
                f"'tools': {sorted(by_name)}"
            )
        return [make(by_name[forced])]

    choice = request.tool_choice if isinstance(request.tool_choice, str) else None
    if choice is None:
        choice = "auto" if tools else "none"

    if choice == "none" or not tools:
        return []

    if (
        profile is not None
        and profile.kind == "search"
        and choice == "auto"
        and _GENERATE_PLAN not in by_name
    ):
        calls = _search_profile_calls(messages, by_name, knobs, profile, snippet)
        if calls is not None:
            return calls

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
        if retrieval_tool is None and (
            calls := _code_mode_retrieval(messages, by_name, 1, snippet)
        ):
            return calls
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
        if not retrieval and (
            calls := _code_mode_retrieval(
                messages, by_name, knobs.n_auto_tools, snippet
            )
        ):
            return calls
        chosen = retrieval[: knobs.n_auto_tools]
        if not chosen and tools:
            chosen = [tools[0]]
        if chosen:
            return [make(t) for t in chosen]
    return []


@dataclass(frozen=True)
class ResponsePlan:
    profile: TurnProfile | None
    phase: Literal["tool", "helper", "answer"]
    answer: str
    reasoning: str
    calls: list[ToolCall]
    finish: str
    usage: Usage
    deltas: list[ChunkDelta]
    first_s: float
    end_s: float


def response_deltas(
    answer: str, reasoning: str, calls: list[ToolCall], *, fragmented: bool
) -> list[ChunkDelta]:
    """Encode prepared content once for streaming and chunk-count metrics."""
    deltas: list[ChunkDelta] = []
    if calls:
        deltas.append(
            ChunkDelta(
                role="assistant",
                tool_calls=[
                    StreamToolCall(
                        index=i,
                        id=call.id,
                        type="function",
                        function=StreamToolCallFunction(
                            name=call.function.name, arguments=""
                        ),
                    )
                    for i, call in enumerate(calls)
                ],
            )
        )
        for i, call in enumerate(calls):
            deltas.extend(
                ChunkDelta(
                    tool_calls=[
                        StreamToolCall(
                            index=i, function=StreamToolCallFunction(arguments=part)
                        )
                    ]
                )
                for part in fragments(call.function.arguments, 12)
            )
    else:
        deltas.extend(
            ChunkDelta(reasoning_content=part) for part in fragments(reasoning, 6)
        )
        chunks = fragments(answer, 6) if fragmented else re.findall(r"\S+\s*", answer)
        deltas.extend(ChunkDelta(content=part) for part in chunks)
        if deltas:
            deltas[0].role = "assistant"
        else:
            deltas.append(ChunkDelta(role="assistant", content=""))
    return deltas


def prepare_response(
    request: ChatCompletionRequest, knobs: Knobs, *, prompt_tokens: int | None = None
) -> ResponsePlan:
    kind = profile_kind(request.model)
    user_text = _last_user_text(request.messages)
    question = current_question(user_text)
    profile = (
        turn_profile(kind, question, int(os.environ.get("MOCK_WORKLOAD_SEED", "0")))
        if kind
        else None
    )
    calls = _pick_tool(request, knobs, profile, question)
    helper = (
        search_helper_answer(
            user_text.strip(),
            selected_count=knobs.selected_count,
            classification=knobs.classification,
        )
        if not calls
        else None
    )
    system = "\n".join(
        m.content
        for m in request.messages
        if m.role == "system" and isinstance(m.content, str)
    )
    echo = helper_kind(user_text.strip(), system) in ("keyword", "semantic")
    if helper is not None:
        answer = helper
    elif echo:
        answer = _echo_answer(request.messages)
        if "standalone keyword queries" in system:
            answer = keyword_query(answer)
    else:
        words = profile.answer_words if profile else knobs.n_tokens
        if re.search(r"-len\d+", request.model):
            words = knobs.n_tokens
        answer = " ".join(_FILLER_WORDS[i % len(_FILLER_WORDS)] for i in range(words))
        if profile and not calls:
            ids = citation_ids(request)
            if ids:
                answer += " " + " ".join(f"[{number}]" for number in ids[:3])
    reasoning = ""
    if (
        profile
        and not calls
        and helper is None
        and not echo
        and profile.reasoning_words
    ):
        reasoning = " ".join(
            ["Checking evidence before answering."] * (profile.reasoning_words // 4)
        )
    if calls:
        answer = ""
    reasoning, reasoning_cut = truncate_tokens(reasoning, request.effective_max_tokens)
    remaining = (
        None
        if request.effective_max_tokens is None
        else max(0, request.effective_max_tokens - token_count(reasoning))
    )
    answer, answer_cut = truncate_tokens(answer, remaining)
    calls, calls_cut = limit_tool_calls(calls, request.effective_max_tokens)
    finish = (
        "length"
        if reasoning_cut or answer_cut or calls_cut
        else "tool_calls"
        if calls
        else "stop"
    )
    if "-faultmalformed" in request.model and calls:
        calls[0].function.arguments = '{"queries": ['
    deltas = response_deltas(answer, reasoning, calls, fragmented=profile is not None)
    first_s = knobs.ttft_s
    end_s = first_s + (0 if calls else knobs.itl_s * len(re.findall(r"\S+", answer)))
    if profile:
        duration = helper_duration(user_text.strip(), system)
        first_s = (
            1.05
            if calls
            else min(0.3, duration)
            if duration is not None
            else profile.first_output_s
        )
        end_s = (
            1.5
            if calls
            else duration
            if duration is not None
            else profile.final_duration_s
        )
        if re.search(r"-ttft\d+", request.model):
            end_s += knobs.ttft_s - first_s
            first_s = knobs.ttft_s
        if re.search(r"-itl\d+", request.model):
            end_s = first_s + knobs.itl_s * len(deltas)
    return ResponsePlan(
        profile=profile,
        phase="tool" if calls else "helper" if helper is not None or echo else "answer",
        answer=answer,
        reasoning=reasoning,
        calls=calls,
        finish=finish,
        usage=usage_for(request, answer, reasoning, calls, prompt_tokens=prompt_tokens),
        deltas=deltas,
        first_s=first_s,
        end_s=max(first_s, end_s),
    )
