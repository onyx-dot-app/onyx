import json
import re
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import GenerationRequest, ReasoningEffort
from onyx.secondary_llm_flows import suggested_questions as sq
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


@pytest.fixture(autouse=True)
def _one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """One writing call, so a test of the rules reads one prompt. The tests of
    the parallel calls set their own number."""
    monkeypatch.setattr(sq, "SQ_WRITING_CALLS", 1)


def _passages(count: int) -> list[InferenceChunk]:
    return [_chunk(f"doc-{n}", content="x" * 2000) for n in range(1, count + 1)]


def _llm(questions: list[dict[str, Any]]) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value.text = json.dumps({"questions": questions})
    return llm


def _prompt_documents(request: GenerationRequest) -> list[str]:
    return re.findall(r"^\[\d+\] (\S+)$", request.messages[1].text, re.MULTILINE)


def _asks_about_every_passage() -> MagicMock:
    """An LLM that writes one question per passage it gets, named after the
    passage's document."""

    def invoke(request: GenerationRequest, context: Any) -> MagicMock:  # noqa: ARG001
        questions = [
            {"passage": number, "question": f"What does {document} say?"}
            for number, document in enumerate(_prompt_documents(request), start=1)
        ]
        return MagicMock(text=json.dumps({"questions": questions}))

    llm = MagicMock()
    llm.invoke.side_effect = invoke
    return llm


def test_write_questions_sends_numbered_passages_and_asks_for_json() -> None:
    llm = _llm([])

    sq.write_questions(
        _passages(sq.SQ_PASSAGES_MAX + 5), [llm], "Acme", ["engineer", "sales"]
    )

    request: GenerationRequest = llm.invoke.call_args.args[0]
    system, user = request.messages
    assert "people at Acme" in system.text and "engineer, sales" in system.text
    assert "Skip every passage with private information" in system.text
    assert user.text.startswith("[1] doc-1\n" + "x" * 800 + "\n\n[2] doc-2")
    # OpenAI's JSON mode needs "json" in the input messages, not only the system.
    assert user.text.endswith("Return the questions as JSON.")
    assert f"[{sq.SQ_PASSAGES_MAX}] " in user.text
    assert f"[{sq.SQ_PASSAGES_MAX + 1}] " not in user.text
    assert request.options.structured_response_format == {"type": "json_object"}
    # Without thinking, the model wrote questions from private passages.
    assert request.options.reasoning_effort == ReasoningEffort.LOW
    context = llm.invoke.call_args.kwargs["context"]
    assert context.flow == LLMFlow.SUGGESTED_QUESTIONS


def test_write_questions_drops_questions_that_break_the_rules() -> None:
    def item(passage: int, question: str, best_for: str = "hr") -> dict[str, Any]:
        return {"passage": passage, "question": question, "best_for": best_for}

    llm = _llm(
        [
            item(1, "How many days of leave do we get?"),
            item(1, "Who approves a trip abroad?", "any"),  # second for doc-1
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
        ("Which team owns the deploy pipeline?", "doc-2", UseCase.ENGINEERING),
    ]


def test_write_questions_keeps_one_question_per_document() -> None:
    passages = [
        _chunk("handbook", 0, "Leave rules."),
        _chunk("handbook", 1, "Travel rules."),
        _chunk("runbook", 0, "Deploy rules."),
    ]
    llm = _llm(
        [
            {"passage": 1, "question": "How many days of leave do we get?"},
            {"passage": 2, "question": "Who approves a trip abroad?"},
            {"passage": 3, "question": "Which team owns the deploy pipeline?"},
        ]
    )

    drafts = sq.write_questions(passages, [llm], None, [])

    assert [(d.text, d.chunk.chunk_id) for d in drafts] == [
        ("How many days of leave do we get?", 0),
        ("Which team owns the deploy pipeline?", 0),
    ]


def test_documents_are_dealt_out_to_calls_that_run_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sq, "SQ_WRITING_CALLS", 3)
    passages = [_chunk(f"doc-{n}") for n in range(1, 8)] + [_chunk("doc-1", 1)]
    llm = _asks_about_every_passage()

    drafts = sq.write_questions(passages, [llm], None, [])

    calls = sorted(
        _prompt_documents(call.args[0]) for call in llm.invoke.call_args_list
    )
    # In turn, so every call gets a mix; doc-1's passages stay in one call.
    assert calls == [
        ["doc-1", "doc-4", "doc-7", "doc-1"],
        ["doc-2", "doc-5"],
        ["doc-3", "doc-6"],
    ]
    # Each call asks for its share of the run's questions.
    share = -(-sq.SQ_QUESTIONS_PER_RUN // 3)
    for call in llm.invoke.call_args_list:
        assert f"Write up to {share} questions." in call.args[0].messages[0].text
    assert sorted(d.chunk.document_id for d in drafts) == [
        f"doc-{n}" for n in range(1, 8)
    ]


def test_each_call_keeps_at_most_its_share(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sq, "SQ_WRITING_CALLS", 2)
    monkeypatch.setattr(sq, "SQ_QUESTIONS_PER_RUN", 4)
    passages = [_chunk(f"doc-{n}") for n in range(1, 11)]

    drafts = sq.write_questions(passages, [_asks_about_every_passage()], None, [])

    # Two per call: neither call can fill the run alone.
    assert sorted(d.chunk.document_id for d in drafts) == [
        "doc-1",
        "doc-2",
        "doc-3",
        "doc-4",
    ]


def test_a_failed_call_loses_only_its_own_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sq, "SQ_WRITING_CALLS", 2)
    working = _asks_about_every_passage()

    def invoke(request: GenerationRequest, context: Any) -> MagicMock:
        if "doc-1" in _prompt_documents(request):
            raise RuntimeError("timed out")
        return working.invoke(request, context)

    llm = MagicMock()
    llm.config.model_name = "fake"
    llm.invoke.side_effect = invoke

    drafts = sq.write_questions(
        [_chunk(f"doc-{n}") for n in (1, 2, 3, 4)], [llm], None, []
    )

    assert sorted(d.chunk.document_id for d in drafts) == ["doc-2", "doc-4"]


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

    with pytest.raises(RuntimeError):
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
            {"passage": 2, "question": "How long is parental leave?"},
        ]
    )

    drafts = sq.write_questions(_passages(2), [llm], None, [])

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

    with pytest.raises(RuntimeError):
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
