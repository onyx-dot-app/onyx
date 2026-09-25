"""Deep Research batch runner: parent pairing, failures, and timeouts."""

import queue
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.deep_research.dr_mock_tools import (
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.deep_research.models import (
    CombinedResearchAgentCallResult,
    ResearchAgentCallFailure,
    ResearchAgentCallResult,
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


def _research_call(call_id: str, tab_index: int) -> ToolCallKickoff:
    return ToolCallKickoff(
        tool_call_id=call_id,
        tool_name=RESEARCH_AGENT_TOOL_NAME,
        tool_args={RESEARCH_AGENT_TASK_KEY: call_id},
        placement=Placement(turn_index=TURN, tab_index=tab_index),
    )


def _run_pairing_batch(
    calls: list[ToolCallKickoff], parent_ids: list[str]
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    def fake_call(
        research_agent_call: ToolCallKickoff,
        parent_tool_call_id: str,
        *_args: Any,
    ) -> ResearchAgentCallResult:
        pairs.append((research_agent_call.tool_call_id, parent_tool_call_id))
        return ResearchAgentCallResult(intermediate_report="r", citation_mapping={})

    with patch.object(research_agent, "run_research_agent_call", fake_call):
        run_research_agent_calls(
            research_agent_calls=calls,
            parent_tool_call_ids=parent_ids,
            tools=[],
            emitter=_emitter(),
            state_container=ChatStateContainer(),
            llm=MagicMock(spec=LLM),
            is_reasoning_model=True,
            token_counter=_token_counter,
            citation_mapping={},
            language_section="",
        )
    return pairs


def test_batch_pairs_each_call_with_its_parent_id() -> None:
    calls = [_research_call("rc1", 0), _research_call("rc2", 1)]

    pairs = _run_pairing_batch(calls, ["rc1", "rc2"])

    assert sorted(pairs) == [("rc1", "rc1"), ("rc2", "rc2")]


def test_batch_rejects_mismatched_parent_ids() -> None:
    calls = [_research_call("rc1", 0)]

    with pytest.raises(ValueError):
        _run_pairing_batch(calls, ["u1", "rc1"])


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
        parent_tool_call_ids=[c.tool_call_id for c in calls],
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
