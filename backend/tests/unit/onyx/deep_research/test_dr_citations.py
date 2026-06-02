"""Unit tests for per-persona `include_citations` gating in the deep-research path.

The deep-research loop only emits user-facing citations from the final report
(`generate_final_report`). That step is the single decision point that selects
the `DynamicCitationProcessor` mode, mirroring `run_llm_loop` for the regular
path: HYPERLINK when citations are enabled, REMOVE when the persona disabled
them. These tests spy on the `citation_processor` handed to `run_llm_step` to
confirm the mode is chosen from `include_citations`, rather than driving the
full multi-cycle loop (which is brittle to set up).
"""

from contextlib import contextmanager
from typing import Any
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from onyx.chat.citation_processor import CitationMode
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import LlmStepResult
from onyx.deep_research import dr_loop


@contextmanager
def _noop_span(*_args: Any, **_kwargs: Any) -> Iterator[MagicMock]:
    yield MagicMock()


@pytest.mark.parametrize(
    "include_citations, expected_mode",
    [
        (True, CitationMode.HYPERLINK),
        (False, CitationMode.REMOVE),
    ],
)
def test_generate_final_report_citation_mode(
    monkeypatch: pytest.MonkeyPatch,
    include_citations: bool,
    expected_mode: CitationMode,
) -> None:
    captured: dict[str, DynamicCitationProcessor | None] = {"processor": None}

    def fake_run_llm_step(*_args: Any, **kwargs: Any) -> tuple[LlmStepResult, bool]:
        captured["processor"] = kwargs["citation_processor"]
        result = LlmStepResult(
            reasoning=None,
            answer="Final report body.",
            tool_calls=None,
        )
        return result, False

    # Isolate the decision point: skip tracing, history construction, and the LLM call.
    monkeypatch.setattr(dr_loop, "run_llm_step", fake_run_llm_step)
    monkeypatch.setattr(dr_loop, "construct_message_history", lambda *a, **k: [])
    monkeypatch.setattr(dr_loop, "function_span", _noop_span)

    llm = MagicMock()
    llm.config.max_input_tokens = 100_000

    has_reasoned = dr_loop.generate_final_report(
        history=[],
        research_plan="plan",
        llm=llm,
        token_counter=len,
        state_container=MagicMock(),
        emitter=MagicMock(),
        turn_index=1,
        citation_mapping={},
        user_identity=None,
        include_citations=include_citations,
    )

    assert has_reasoned is False
    processor = captured["processor"]
    assert isinstance(processor, DynamicCitationProcessor)
    assert processor.citation_mode is expected_mode
