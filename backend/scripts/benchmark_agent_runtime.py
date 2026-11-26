"""Measure the CPU, latency and memory of long chats on the agent runtime.

Runs real chat agents (`ChatAgent`) on the real runtime, event delivery and
response presenter, with the real LiteLLM wrapper up to the provider stream.
A scripted provider stream gives thinking and one search call per step, then
an answer. The search tool returns search passages in the real result format,
whose documents repeat across steps. Model and tool latency are simulated
sleeps. No external service is needed.

The defaults stay within the product's limits: at most MAX_LLM_CYCLES steps
and DEFAULT_MAX_OUTPUT_CHARS characters per tool result. The default result
size is about the mean search output of the EnterpriseRAG benchmark.

It reports throughput, latency, CPU, peak RSS and garbage collection time, and
how many runs and search documents stay alive after the chats return, before
and after a garbage collection pass.

Usage:
    cd backend && uv run python -m scripts.benchmark_agent_runtime \
        [--chats 24] [--steps 25] [--result-chars 16000] [--llm-latency 0.5] \
        [--tool-latency 0.3] [--json-out report.json]
"""

import argparse
import gc
import json
import random
import statistics
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import override

import psutil
from pydantic import JsonValue

from onyx.agents.runtime import Run
from onyx.agents.tools import ToolInvocation
from onyx.chat.agent import ChatAgent
from onyx.chat.emitter import Emitter
from onyx.chat.models import SearchPassage, SearchPassages
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.stream_buffer import ChatDelivery
from onyx.configs.chat_configs import LLM_SOCKET_READ_TIMEOUT, MAX_LLM_CYCLES
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.model_request import ChatCompletionMessage
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
)
from onyx.llm.models import (
    ReasoningEffort,
    ToolChoice,
    ToolDefinition,
    ToolResult,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM, ProviderOperation
from onyx.tools.constants import DEFAULT_MAX_OUTPUT_CHARS
from onyx.tools.interface import Tool
from onyx.tools.models import CodeModeExposure, ToolContext
from onyx.tools.ordering import ToolRank

DOCUMENT_POOL = 4000
DOCUMENTS_PER_SEARCH = 15
THINKING_CHARS = 1_500
ANSWER_CHARS = 3_000
DELTA_CHARS = 30

_WORDS = random.Random(7)
CORPUS = " ".join(
    "".join(_WORDS.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6))
    for _ in range(400_000)
)


def _text(rng: random.Random, length: int) -> str:
    start = rng.randrange(0, len(CORPUS) - length)
    return CORPUS[start : start + length]


class BenchLLM(LitellmLLM):
    """The LiteLLM wrapper with a scripted provider stream: the model thinks,
    then searches on every step but the last."""

    def __init__(self, steps: int, rng: random.Random, latency_s: float) -> None:
        super().__init__(
            api_key=None,
            model_provider="openai",
            model_name="bench-model",
            max_input_tokens=10_000_000,
            temperature=0,
        )
        self.steps = steps
        self.calls = 0
        self.rng = rng
        self.latency_s = latency_s

    @override
    def stream_raw(
        self,
        prompt: list[ChatCompletionMessage],
        tools: list[dict[str, JsonValue]] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict[str, JsonValue] | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        stall_timeout_s: int = LLM_SOCKET_READ_TIMEOUT,
        operation: ProviderOperation | None = None,
        manage_tool_strictness: bool = False,
    ) -> Iterator[ModelResponseStream]:
        index = self.calls
        self.calls += 1
        final = index >= self.steps - 1
        thinking = _text(self.rng, THINKING_CHARS)
        deltas = [
            Delta(reasoning_content=thinking[start : start + DELTA_CHARS])
            for start in range(0, len(thinking), DELTA_CHARS)
        ]
        if final:
            answer = _text(self.rng, ANSWER_CHARS)
            deltas.extend(
                Delta(content=answer[start : start + DELTA_CHARS])
                for start in range(0, len(answer), DELTA_CHARS)
            )
        else:
            deltas.append(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id=f"call_{index}",
                            index=0,
                            function=ResponseFunctionCall(
                                name="lookup",
                                arguments=json.dumps({"query": _text(self.rng, 60)}),
                            ),
                        )
                    ]
                )
            )
        pause = self.latency_s / len(deltas)
        for position, delta in enumerate(deltas):
            time.sleep(pause)
            yield ModelResponseStream(
                id="bench",
                created="1",
                choice=StreamingChoice(
                    delta=delta,
                    finish_reason=("stop" if final else "tool_calls")
                    if position == len(deltas) - 1
                    else None,
                ),
            )


class BenchSearchTool(Tool):
    """Returns search passages of documents from a shared pool."""

    rank = ToolRank.INTEGRATION

    def __init__(self, latency_s: float, result_chars: int) -> None:
        self.latency_s = latency_s
        self.result_chars = result_chars

    @property
    def id(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return "lookup"

    @property
    def description(self) -> str:
        return "Search the documents."

    @property
    def display_name(self) -> str:
        return "Lookup"

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        rng = random.Random(invocation.call_id)
        time.sleep(self.latency_s)
        numbers = rng.sample(range(DOCUMENT_POOL), DOCUMENTS_PER_SEARCH)
        documents = [
            SearchDoc(
                document_id=f"https://docs.example.com/{number:06d}",
                chunk_ind=0,
                semantic_identifier=_text(rng, 60),
                link=f"https://docs.example.com/{number:06d}",
                blurb=_text(rng, 500),
                source_type=DocumentSource.CONFLUENCE,
                boost=0,
                hidden=False,
                metadata={"author": _text(rng, 20)},
                score=rng.random(),
                match_highlights=[_text(rng, 200) for _ in range(3)],
                updated_at=None,
                primary_owners=None,
                secondary_owners=None,
                is_internet=False,
            )
            for number in numbers
        ]
        first = context.next_citation_num
        passage_chars = self.result_chars // DOCUMENTS_PER_SEARCH - 60
        return ToolResult(
            content=SearchPassages(
                results=[
                    SearchPassage(
                        document=first + offset,
                        content=_text(rng, passage_chars),
                        title=document.semantic_identifier,
                    )
                    for offset, document in enumerate(documents)
                ]
            ).model_dump_json(),
            details=SearchDocsResponse(
                search_docs=documents,
                citation_mapping={
                    first + offset: document.document_id
                    for offset, document in enumerate(documents)
                },
            ),
        )


def run_chat(
    index: int,
    steps: int,
    result_chars: int,
    llm_latency_s: float,
    tool_latency_s: float,
) -> float:
    """Run one chat to its answer and delivered stream; return its latency."""
    started = time.perf_counter()
    agent = ChatAgent(
        messages=[],
        tools=[BenchSearchTool(tool_latency_s, result_chars)],
        custom_agent_prompt=None,
        base_system_prompt=_text(random.Random(index), 12_000),
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        persona=None,
        user_memory_context=None,
        llm=BenchLLM(steps, random.Random(1000 + index), llm_latency_s),
    )
    delivery = ChatDelivery(None)
    presenter = ResponsePresenter(Emitter(delivery.publish))
    reader = threading.Thread(target=lambda: list(delivery.reader), daemon=True)
    reader.start()
    run = agent.start(
        background=False,
        max_steps=steps,
        messages=[UserMessage(content="What changed in the data platform roadmap?")],
        event_dispatcher=delivery.events,
        on_event=presenter.consume,
    )
    run.result()
    run.wait_for_idle()
    delivery.finish()
    delivery.finished.result(timeout=600)
    reader.join(timeout=600)
    return time.perf_counter() - started


def _live(kind: type) -> int:
    return sum(1 for item in gc.get_objects() if type(item) is kind)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chats", type=int, default=24)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--result-chars", type=int, default=16_000)
    parser.add_argument("--llm-latency", type=float, default=0.5)
    parser.add_argument("--tool-latency", type=float, default=0.3)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    if not 2 <= args.steps <= MAX_LLM_CYCLES:
        parser.error(f"--steps must be between 2 and MAX_LLM_CYCLES ({MAX_LLM_CYCLES})")
    if not 1_000 <= args.result_chars <= DEFAULT_MAX_OUTPUT_CHARS:
        parser.error(
            "--result-chars must be between 1000 and DEFAULT_MAX_OUTPUT_CHARS "
            f"({DEFAULT_MAX_OUTPUT_CHARS})"
        )

    run_chat(-1, 3, args.result_chars, 0.0, 0.0)
    gc.collect()
    gc_seconds = [0.0, 0.0, 0.0]
    gc_started = [0.0]

    def time_collections(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            gc_started[0] = time.perf_counter()
        else:
            gc_seconds[info["generation"]] += time.perf_counter() - gc_started[0]

    gc.callbacks.append(time_collections)
    process = psutil.Process()
    rss_base = process.memory_info().rss
    rss_peak = [rss_base]
    stop = threading.Event()

    def sample_rss() -> None:
        while not stop.wait(0.05):
            rss_peak[0] = max(rss_peak[0], process.memory_info().rss)

    sampler = threading.Thread(target=sample_rss, daemon=True)
    sampler.start()
    latencies: list[float] = []
    cpu_started = time.process_time()
    started = time.perf_counter()
    threads = [
        threading.Thread(
            target=lambda index=index: latencies.append(
                run_chat(
                    index,
                    args.steps,
                    args.result_chars,
                    args.llm_latency,
                    args.tool_latency,
                )
            )
        )
        for index in range(args.chats)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - started
    cpu = time.process_time() - cpu_started
    stop.set()
    sampler.join()
    gc.callbacks.remove(time_collections)
    if len(latencies) != args.chats:
        sys.exit("A chat failed; see the log above")
    report = {
        "chats": args.chats,
        "steps": args.steps,
        "result_chars": args.result_chars,
        "wall_s": round(wall, 2),
        "cpu_s": round(cpu, 2),
        "cpu_per_chat_s": round(cpu / args.chats, 3),
        "chats_per_min": round(args.chats / wall * 60, 2),
        "latency_mean_s": round(statistics.mean(latencies), 2),
        "latency_max_s": round(max(latencies), 2),
        "rss_base_mb": round(rss_base / 2**20),
        "rss_peak_mb": round(rss_peak[0] / 2**20),
        "gc_seconds_by_generation": [round(seconds, 2) for seconds in gc_seconds],
        "live_runs_before_gc": _live(Run),
        "live_search_docs_before_gc": _live(SearchDoc),
    }
    gc.collect()
    report["live_runs_after_gc"] = _live(Run)
    report["live_search_docs_after_gc"] = _live(SearchDoc)
    output = json.dumps(report, indent=2)
    print(output)
    if args.json_out is not None:
        args.json_out.write_text(output)


if __name__ == "__main__":
    main()
