import re
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.llm.decisions.models import (
    ChoiceAnswer,
    DecisionAnswer,
    DecisionProvider,
    DecisionRequest,
    DecisionResponse,
    PredicateAnswer,
    RefusalAnswer,
    ScoreAnswer,
)
from onyx.secondary_llm_flows import suggested_questions as triage
from onyx.server.features.suggested_questions.models import UseCase
from onyx.tracing.flows import LLMFlow


def _chunk(document_id: str, chunk_id: int = 0, content: str = "") -> InferenceChunk:
    return InferenceChunk(
        document_id=document_id,
        chunk_id=chunk_id,
        content=content or f"Text of {document_id}",
        source_type=DocumentSource.GOOGLE_DRIVE,
        semantic_identifier=document_id,
        title=document_id,
        boost=1,
        score=None,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb="",
    )


def _answers(index: int, verdict: dict[str, Any]) -> list[DecisionAnswer]:
    """Answers for excerpt [index]. A verdict value of None is a refusal."""

    def answer(name: str, default: Any, make: Any) -> DecisionAnswer:
        value = verdict.get(name, default)
        name = f"{name}_{index}"
        return RefusalAnswer(name=name) if value is None else make(name, value)

    return [
        answer(
            "usable",
            2,
            lambda n, v: ScoreAnswer(name=n, score=v, confidence=1, probabilities=[]),
        ),
        answer("sensitive", 0.0, lambda n, v: PredicateAnswer(name=n, probability=v)),
        answer(
            "topic",
            "hr",
            lambda n, v: ChoiceAnswer(name=n, choice=v, confidence=1, probabilities=[]),
        ),
        answer("fact", 1.0, lambda n, v: PredicateAnswer(name=n, probability=v)),
    ]


def _client(verdicts: dict[str, dict[str, Any]] | None = None) -> MagicMock:
    """A fake decision client that answers per document id, read back from the
    numbered excerpts in the request."""

    def decide(request: DecisionRequest, flow: LLMFlow) -> DecisionResponse:
        assert flow == LLMFlow.SUGGESTED_QUESTIONS_TRIAGE
        answers: list[DecisionAnswer] = []
        for index, document_id in re.findall(
            r"\[(\d+)\] Document: (\S+)", request.input
        ):
            answers += _answers(int(index), (verdicts or {}).get(document_id, {}))
        return DecisionResponse(model="fake", answers=answers)

    client = MagicMock()
    client.provider = DecisionProvider.OPENAI
    client.decide.side_effect = decide
    return client


def _ids(triaged: list[triage.TriagedChunk]) -> list[str]:
    return [item.chunk.document_id for item in triaged]


def test_keeps_useful_chunks_and_drops_private_ones() -> None:
    client = _client(
        {
            "useless": {"usable": 0.5},
            "private": {"sensitive": 0.3},
            "refused-privacy": {"sensitive": None},
            "refused-usable": {"usable": None},
            "engineering": {"topic": "engineering", "fact": 0.2},
            "refused-topic": {"topic": None},
        }
    )
    names = "useful useless private refused-privacy refused-usable engineering refused-topic"
    chunks = [_chunk(document_id) for document_id in names.split()]

    kept = triage.triage_chunks(chunks, [client])

    assert _ids(kept) == ["useful", "engineering", "refused-topic"]
    assert [item.topic for item in kept] == [UseCase.HR, UseCase.ENGINEERING, None]
    assert kept[1].has_fact == 0.2


def test_asks_four_questions_per_chunk_on_a_short_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(triage, "SQ_TRIAGE_SNIPPET_CHARS", 10)
    client = _client()

    triage.triage_chunks([_chunk("doc", content="0123456789 cut here")], [client])

    request: DecisionRequest = client.decide.call_args.args[0]
    names = [question.name for question in request.questions]
    assert names == ["usable_0", "sensitive_0", "topic_0", "fact_0"]
    assert request.input == "[0] Document: doc\n0123456789"


def test_splits_chunks_into_requests_of_fifty() -> None:
    client = _client()

    kept = triage.triage_chunks([_chunk(f"doc-{i}") for i in range(120)], [client])

    sizes = sorted(len(call.args[0].questions) for call in client.decide.call_args_list)
    assert sizes == [80, 200, 200]
    assert len(kept) == 120


def _refuses_everything(request: DecisionRequest, flow: LLMFlow) -> DecisionResponse:  # noqa: ARG001
    return DecisionResponse(
        model="fake",
        answers=[RefusalAnswer(name=question.name) for question in request.questions],
    )


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("down"), ValueError("bad answer"), _refuses_everything],
    ids=["http_error", "invalid_response", "refuses_everything"],
)
def test_falls_back_to_the_next_provider(failure: Any) -> None:
    failing = _client()
    failing.decide.side_effect = failure
    second = _client()

    kept = triage.triage_chunks([_chunk("doc")], [failing, second])

    assert _ids(kept) == ["doc"]
    second.decide.assert_called_once()


@pytest.mark.parametrize("has_provider", [True, False], ids=["all_fail", "none_set_up"])
def test_rules_decide_when_no_provider_answers(has_provider: bool) -> None:
    failing = _client()
    failing.decide.side_effect = httpx.ConnectError("down")
    chunks = [
        _chunk("early-with-number", 0, "Employees get 25 days of leave a year."),
        _chunk("early-with-name", 1, "Requests go to the People team for approval."),
        _chunk("late", 5, "Employees get 25 days of leave a year."),
        _chunk("plain", 0, "employees can take leave when they need it."),
        _chunk("pay", 0, "The salary band for level 3 is 120k."),
    ]

    kept = triage.triage_chunks(chunks, [failing] if has_provider else [])

    assert _ids(kept) == ["early-with-number", "early-with-name"]
    assert all(item.topic is None for item in kept)


def test_build_triage_clients_tries_openai_then_zoom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[tuple[DecisionProvider, str]] = []

    def get_client(provider: DecisionProvider, model: str) -> MagicMock | None:
        requested.append((provider, model))
        return None if provider == DecisionProvider.ZOOM_AI else MagicMock()

    monkeypatch.setattr(triage, "get_decision_client_for_provider", get_client)

    clients = triage.build_triage_clients()

    assert requested == [
        (DecisionProvider.OPENAI, "gpt-6-luna"),
        (DecisionProvider.ZOOM_AI, "zoom-decisions-pro"),
    ]
    assert len(clients) == 1
