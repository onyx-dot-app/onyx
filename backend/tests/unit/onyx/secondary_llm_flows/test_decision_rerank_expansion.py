from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import (
    ContextExpansionType,
    InferenceChunk,
    InferenceSection,
)
from onyx.llm.decisions.models import (
    DecisionRequest,
    DecisionResponse,
    PredicateAnswer,
    PredicateQuestion,
    RefusalAnswer,
    ScoreAnswer,
    ScoreProbability,
)
from onyx.secondary_llm_flows.decision_rerank_expansion import (
    MAX_DECISION_QUESTIONS,
    decide_context_expansion,
    rank_sections_listwise,
)
from onyx.tracing.flows import LLMFlow


def _section(index: int) -> InferenceSection:
    chunk = InferenceChunk(
        document_id=f"doc-{index}",
        chunk_id=0,
        content=f"content {index}",
        source_type=DocumentSource.GITHUB,
        semantic_identifier=f"Doc {index}",
        title=f"Doc {index}",
        boost=1,
        score=0.5,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb=f"content {index}",
    )
    return InferenceSection(
        center_chunk=chunk, chunks=[chunk], combined_content=chunk.content
    )


def _client(*answers: PredicateAnswer | RefusalAnswer | ScoreAnswer) -> MagicMock:
    client = MagicMock()
    client.decide.return_value = DecisionResponse(
        model="decision-model", answers=list(answers)
    )
    return client


def test_listwise_ranking_asks_one_question_per_section_in_one_request() -> None:
    client = _client(
        PredicateAnswer(name="s0", probability=0.2),
        RefusalAnswer(name="s1"),
        PredicateAnswer(name="s2", probability=0.9),
    )

    scores = rank_sections_listwise(
        [_section(0), _section(1), _section(2)], "which doc?", client
    )

    assert scores == [0.2, 0.0, 0.9]
    client.decide.assert_called_once()
    request: DecisionRequest = client.decide.call_args.args[0]
    assert client.decide.call_args.kwargs["flow"] == LLMFlow.SEARCH_SECTION_RERANK
    assert [question.name for question in request.questions] == ["s0", "s1", "s2"]
    assert all(isinstance(q, PredicateQuestion) for q in request.questions)
    assert request.input.startswith("Query: which doc?")
    assert "[2] Document: Doc 2\ncontent 2" in request.input


def test_listwise_ranking_raises_when_every_question_is_refused() -> None:
    client = _client(RefusalAnswer(name="s0"), RefusalAnswer(name="s1"))

    with pytest.raises(ValueError):
        rank_sections_listwise([_section(0), _section(1)], "query", client)


def test_listwise_ranking_rejects_more_sections_than_one_request_holds() -> None:
    sections = [_section(index) for index in range(MAX_DECISION_QUESTIONS + 1)]

    with pytest.raises(ValueError):
        rank_sections_listwise(sections, "query", MagicMock())


def _expansion_answer(probabilities: list[float]) -> ScoreAnswer:
    return ScoreAnswer(
        name="expansion",
        score=0.0,
        confidence=1.0,
        probabilities=[
            ScoreProbability(value=value, label=str(value), probability=probability)
            for value, probability in enumerate(probabilities)
        ],
    )


def test_expansion_takes_the_most_likely_level() -> None:
    client = _client(_expansion_answer([0.1, 0.2, 0.6, 0.1]))

    result = decide_context_expansion(
        document_title="Doc",
        section_text="main",
        user_query="query",
        client=client,
        section_above_text="above",
        section_below_text=None,
    )

    assert result == ContextExpansionType.INCLUDE_ADJACENT_SECTIONS
    assert (
        client.decide.call_args.kwargs["flow"]
        == LLMFlow.SEARCH_CONTEXT_EXPANSION_DECISION
    )


def test_expansion_without_neighbors_keeps_the_main_section() -> None:
    client = _client(_expansion_answer([0.0, 0.0, 0.1, 0.9]))

    result = decide_context_expansion(
        document_title="Doc",
        section_text="main",
        user_query="query",
        client=client,
        section_above_text=None,
        section_below_text=None,
    )

    assert result == ContextExpansionType.MAIN_SECTION_ONLY


def test_expansion_refusal_raises_so_the_caller_falls_back() -> None:
    client = _client(RefusalAnswer(name="expansion"))

    with pytest.raises(ValueError):
        decide_context_expansion(
            document_title="Doc",
            section_text="main",
            user_query="query",
            client=client,
            section_above_text="above",
            section_below_text="below",
        )
