"""Deep Research batch runner: failures and timeouts."""

import queue
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.deep_research.models import (
    CombinedResearchAgentCallResult,
    ResearchAgentCallFailure,
    ResearchAgentCallResult,
)
from onyx.deep_research.tool_definitions import (
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.fake_tools import research_agent
from onyx.tools.fake_tools.research_agent import (
    RESEARCH_AGENT_FAILURE_MESSAGE,
    RESEARCH_AGENT_TIMEOUT_MESSAGE,
    run_research_agent_calls,
)
from onyx.tools.models import ToolCallKickoff

TURN = 2


def _emitter() -> Emitter:
    merged: queue.Queue[tuple[int, Packet | Exception | object]] = queue.Queue()
    return Emitter(merged_queue=merged)


def _token_counter(value: str) -> int:
    return len(value) // 4 + 1


def _search_doc(document_id: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier=f"Doc {document_id}",
        link=f"https://example.com/{document_id}",
        blurb=f"blurb for {document_id}",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        score=1.0,
        match_highlights=[],
    )


def _child_result(report: str, doc_ids: list[str]) -> ResearchAgentCallResult:
    return ResearchAgentCallResult(
        intermediate_report=report,
        citation_mapping={
            number: _search_doc(doc_id)
            for number, doc_id in enumerate(doc_ids, start=1)
        },
    )


def _calls(tasks: list[str]) -> list[ToolCallKickoff]:
    return [
        ToolCallKickoff(
            tool_call_id=f"rc{i}",
            tool_name=RESEARCH_AGENT_TOOL_NAME,
            tool_args={RESEARCH_AGENT_TASK_KEY: task},
            placement=Placement(turn_index=TURN, tab_index=i),
        )
        for i, task in enumerate(tasks)
    ]


def _run_batch(calls: list[ToolCallKickoff]) -> CombinedResearchAgentCallResult:
    return run_research_agent_calls(
        research_agent_calls=calls,
        tools=[],
        emitter=_emitter(),
        state_container=ChatStateContainer(),
        llm=MagicMock(spec=LLM),
        is_reasoning_model=True,
        token_counter=_token_counter,
        citation_mapping={},
        language_section="",
    )


class TestResearchBatch:
    def test_results_keep_call_order_and_failed_positions(self) -> None:
        results_by_task: dict[str, tuple[float, ResearchAgentCallResult | None]] = {
            "first": (0.15, _child_result("First [1].", ["d1"])),
            "second": (0.0, None),
            "third": (0.05, _child_result("Third [1].", ["d3"])),
        }

        def fake_child(call: ToolCallKickoff, *_args: Any) -> Any:
            delay, result = results_by_task[call.tool_args[RESEARCH_AGENT_TASK_KEY]]
            time.sleep(delay)
            return result

        with patch.object(research_agent, "run_research_agent_call", fake_child):
            combined = _run_batch(_calls(["first", "second", "third"]))

        assert combined.intermediate_reports == [
            "First [1].",
            ResearchAgentCallFailure(message=RESEARCH_AGENT_FAILURE_MESSAGE),
            "Third [2].",
        ]
        assert {n: d.document_id for n, d in combined.citation_mapping.items()} == {
            1: "d1",
            2: "d3",
        }

    def test_timed_out_child_returns_timeout_failure(self) -> None:
        release = threading.Event()

        def fake_child(call: ToolCallKickoff, *_args: Any) -> Any:
            if call.tool_args[RESEARCH_AGENT_TASK_KEY] == "slow":
                release.wait(timeout=5)
                return _child_result("Too late.", ["late"])
            return _child_result("Fast [1].", ["f"])

        try:
            with (
                patch.object(research_agent, "run_research_agent_call", fake_child),
                patch.object(research_agent, "RESEARCH_AGENT_TIMEOUT_SECONDS", 1.0),
            ):
                combined = _run_batch(_calls(["slow", "fast"]))
        finally:
            release.set()

        assert combined.intermediate_reports == [
            ResearchAgentCallFailure(message=RESEARCH_AGENT_TIMEOUT_MESSAGE),
            "Fast [1].",
        ]
        assert {n: d.document_id for n, d in combined.citation_mapping.items()} == {
            1: "f"
        }
