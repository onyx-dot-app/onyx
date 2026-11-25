import json
import re
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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
from onyx.llm.models import GenerationRequest, ReasoningEffort
from onyx.secondary_llm_flows import suggested_questions as sq
from onyx.server.features.suggested_questions.models import TriagedChunk, UseCase
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


def _ids(triaged: list[sq.TriagedChunk]) -> list[str]:
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

    kept = sq.triage_chunks(chunks, [client])

    assert _ids(kept) == ["useful", "engineering", "refused-topic"]
    assert [item.topic for item in kept] == [UseCase.HR, UseCase.ENGINEERING, None]
    assert kept[1].has_fact == 0.2


def test_asks_four_questions_per_chunk_on_a_short_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sq, "SQ_TRIAGE_SNIPPET_CHARS", 10)
    client = _client()

    sq.triage_chunks([_chunk("doc", content="0123456789 cut here")], [client])

    request: DecisionRequest = client.decide.call_args.args[0]
    names = [question.name for question in request.questions]
    assert names == ["usable_0", "sensitive_0", "topic_0", "fact_0"]
    assert request.input == "[0] Document: doc\n0123456789"


def test_splits_chunks_into_requests_of_fifty() -> None:
    client = _client()

    kept = sq.triage_chunks([_chunk(f"doc-{i}") for i in range(120)], [client])

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

    kept = sq.triage_chunks([_chunk("doc")], [failing, second])

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

    kept = sq.triage_chunks(chunks, [failing] if has_provider else [])

    assert _ids(kept) == ["early-with-number", "early-with-name"]
    assert all(item.topic is None for item in kept)


def test_build_triage_clients_tries_openai_then_zoom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[tuple[DecisionProvider, str]] = []

    def get_client(provider: DecisionProvider, model: str) -> MagicMock | None:
        requested.append((provider, model))
        return None if provider == DecisionProvider.ZOOM_AI else MagicMock()

    monkeypatch.setattr(sq, "get_decision_client_for_provider", get_client)

    clients = sq.build_triage_clients()

    assert requested == [
        (DecisionProvider.OPENAI, "gpt-6-luna"),
        (DecisionProvider.ZOOM_AI, "zoom-decisions-pro"),
    ]
    assert len(clients) == 1


def test_a_full_refusal_keeps_nothing_even_when_rules_would() -> None:
    refusing = _client()
    refusing.decide.side_effect = _refuses_everything
    # The rules alone would keep this chunk: early, with a number.
    chunk = _chunk("address", 0, "Alice's home address is 25 Oak Street.")

    assert sq.triage_chunks([chunk], [refusing]) == []


@pytest.mark.parametrize(
    "error",
    [OnyxError(OnyxErrorCode.RATE_LIMITED, "over the cost limit"), ValueError("bad")],
    ids=["cost_limit", "set_up_wrong"],
)
def test_build_triage_clients_skips_a_provider_it_cannot_use(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def get_client(provider: DecisionProvider, model: str) -> MagicMock:  # noqa: ARG001
        if provider == DecisionProvider.OPENAI:
            raise error
        return MagicMock()

    monkeypatch.setattr(sq, "get_decision_client_for_provider", get_client)

    assert len(sq.build_triage_clients()) == 1


def _passages(count: int) -> list[TriagedChunk]:
    return [
        TriagedChunk(
            chunk=_chunk(f"doc-{n}", content="x" * 2000),
            usable=2,
            sensitive=0,
            topic=None,
            has_fact=1,
        )
        for n in range(1, count + 1)
    ]


def _llm(questions: list[dict[str, Any]]) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value.text = json.dumps({"questions": questions})
    return llm


def test_write_questions_sends_numbered_passages_and_asks_for_json() -> None:
    llm = _llm([])

    sq.write_questions(_passages(25), [llm], "Acme", ["engineer", "sales"])

    request: GenerationRequest = llm.invoke.call_args.args[0]
    system, user = request.messages
    assert "people at Acme" in system.text and "engineer, sales" in system.text
    assert user.text.startswith("[1] doc-1\n" + "x" * 1400 + "\n\n[2] doc-2")
    # OpenAI's JSON mode needs "json" in the input messages, not only the system.
    assert user.text.endswith("Return the questions as JSON.")
    assert "[21]" not in user.text  # at most 20 passages
    assert request.options.structured_response_format == {"type": "json_object"}
    assert request.options.reasoning_effort == ReasoningEffort.OFF
    context = llm.invoke.call_args.kwargs["context"]
    assert context.flow == LLMFlow.SUGGESTED_QUESTIONS


def test_write_questions_drops_questions_that_break_the_rules() -> None:
    def item(passage: int, question: str, best_for: str = "hr") -> dict[str, Any]:
        return {"passage": passage, "question": question, "best_for": best_for}

    llm = _llm(
        [
            item(1, "How many days of leave do we get?"),
            item(1, "Who approves a trip abroad?", "any"),
            item(1, "What is the third question?"),  # over 2 per passage
            item(2, "How many days of leave do we get?"),  # duplicate
            item(2, "Is remote work allowed?"),  # yes/no
            item(2, "What does the document say about travel?"),  # names the source
            item(2, "What is the travel budget"),  # not a question
            item(2, "What is " + "very " * 20 + "long?"),  # too long
            item(9, "Which passage does not exist?"),
            item(2, "Which team owns the deploy pipeline?", "engineering"),
        ]
    )

    drafts = sq.write_questions(_passages(2), [llm], None, [])

    assert [(d.text, d.chunk.document_id, d.best_for) for d in drafts] == [
        ("How many days of leave do we get?", "doc-1", UseCase.HR),
        ("Who approves a trip abroad?", "doc-1", None),
        ("Which team owns the deploy pipeline?", "doc-2", UseCase.ENGINEERING),
    ]


def test_write_questions_reads_json_inside_a_code_block() -> None:
    llm = MagicMock()
    question = {"passage": 1, "question": "Who approves leave?", "best_for": "hr"}
    llm.invoke.return_value.text = (
        "Here you go:\n```json\n" + json.dumps({"questions": [question]}) + "\n```"
    )

    drafts = sq.write_questions(_passages(1), [llm], None, [])

    assert [draft.text for draft in drafts] == ["Who approves leave?"]


@pytest.mark.parametrize("text", ["not json", '{"questions": "wrong shape"}'])
def test_write_questions_raises_on_invalid_output(text: str) -> None:
    llm = MagicMock()
    llm.invoke.return_value.text = text

    with pytest.raises(ValueError):
        sq.write_questions(_passages(1), [llm], None, [])


@pytest.mark.parametrize(
    "question, kept",
    [
        ("Am I eligible for parental leave?", False),
        ("May I carry over unused leave?", False),
        ("Must I get approval for a trip abroad?", False),
        ("Shall we use the new deploy pipeline?", False),
        ("Isn't the office closed on Fridays?", False),
        ("Can't I expense a home desk?", False),
        ("How many days of leave do we get?", True),
        ("Which team owns the deploy pipeline?", True),
        ("Mayor's office: who is the contact?", True),
        ("Docs for the API: where do they live?", True),
    ],
)
def test_write_questions_drops_yes_no_questions(question: str, kept: bool) -> None:
    llm = _llm([{"passage": 1, "question": question, "best_for": "hr"}])

    drafts = sq.write_questions(_passages(1), [llm], None, [])

    assert bool(drafts) is kept


@pytest.mark.parametrize(
    "best_for, expected",
    [
        ("hr", UseCase.HR),
        (" Sales ", UseCase.SALES),
        ("ENGINEERING", UseCase.ENGINEERING),
        ("any", None),
        ("other", None),
        ("finance", None),
        (None, None),
        (3, None),
    ],
)
def test_best_for_never_fails_the_output(best_for: Any, expected: Any) -> None:
    llm = _llm(
        [
            {"passage": 1, "question": "Who approves leave?", "best_for": best_for},
            # No best_for at all.
            {"passage": 1, "question": "How long is parental leave?"},
        ]
    )

    drafts = sq.write_questions(_passages(1), [llm], None, [])

    assert [draft.best_for for draft in drafts] == [expected, None]


def test_write_questions_falls_back_to_the_next_model() -> None:
    failing = MagicMock()
    failing.invoke.side_effect = RuntimeError("no credits remaining")
    fallback = _llm(
        [{"passage": 1, "question": "Who approves leave?", "best_for": "hr"}]
    )

    drafts = sq.write_questions(_passages(1), [failing, fallback], None, [])

    assert [draft.text for draft in drafts] == ["Who approves leave?"]


def test_write_questions_raises_when_every_model_fails() -> None:
    first, second = MagicMock(), MagicMock()
    first.invoke.side_effect = RuntimeError("down")
    second.invoke.return_value.text = "not json"

    with pytest.raises(ValueError):
        sq.write_questions(_passages(1), [first, second], None, [])
    with pytest.raises(ValueError):
        sq.write_questions(_passages(1), [], None, [])


def test_build_writing_llms_tries_openai_then_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[tuple[str, str]] = []

    def get_llm(provider: str, model: str) -> MagicMock | None:
        requested.append((provider, model))
        if provider == "openai":
            raise OnyxError(OnyxErrorCode.RATE_LIMITED, "over the cost limit")
        return MagicMock()

    monkeypatch.setattr(sq, "get_llm_for_provider", get_llm)

    llms = sq.build_writing_llms()

    assert requested == [("openai", "gpt-6-luna"), ("anthropic", "claude-haiku-5-5")]
    assert len(llms) == 1
