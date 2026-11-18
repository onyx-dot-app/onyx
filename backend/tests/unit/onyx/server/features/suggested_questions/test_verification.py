from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.db.models import User
from onyx.server.features.suggested_questions import verification
from onyx.server.features.suggested_questions.models import (
    DraftQuestion,
    QuestionKind,
    UseCase,
)


def _chunk(
    document_id: str, source: DocumentSource = DocumentSource.GOOGLE_DRIVE
) -> InferenceChunk:
    return InferenceChunk(
        document_id=document_id,
        chunk_id=0,
        content="text",
        source_type=source,
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


@pytest.fixture
def searches(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Each question's search returns chunks of these documents, in order."""
    state: dict[str, Any] = {"results": {}, "as_user": [], "acl_builds": 0}
    monkeypatch.setattr(verification, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(verification, "get_current_search_settings", MagicMock())
    monkeypatch.setattr(verification, "get_default_document_index", MagicMock())
    monkeypatch.setattr(verification, "EmbeddingModel", MagicMock())

    def build_acl(*_args: Any) -> MagicMock:
        state["acl_builds"] += 1
        return MagicMock()

    monkeypatch.setattr(verification, "build_access_filters_for_user", build_acl)

    def search_everything(query: str, *_args: Any) -> list[InferenceChunk]:
        return [_chunk(document_id) for document_id in state["results"][query]]

    def search_as(
        user: User, _acl: Any, query: str, *_args: Any
    ) -> list[InferenceChunk]:
        state["as_user"].append(user.email)
        return search_everything(query)

    monkeypatch.setattr(verification, "_search_everything", search_everything)
    monkeypatch.setattr(verification, "_search_as", search_as)
    return state


def test_keeps_questions_whose_document_is_in_the_top_three(
    searches: dict[str, Any],
) -> None:
    searches["results"] = {
        # Repeated chunks of one document count once.
        "first?": ["a", "a", "other"],
        "third?": ["x", "x", "y", "c", "z"],
        "fourth?": ["x", "y", "z", "d"],
        "missing?": ["x"],
    }
    drafts = [
        DraftQuestion(text="first?", chunk=_chunk("a"), best_for=UseCase.HR),
        DraftQuestion(
            text="third?", chunk=_chunk("c", DocumentSource.USER_FILE), best_for=None
        ),
        DraftQuestion(text="fourth?", chunk=_chunk("d"), best_for=None),
        DraftQuestion(text="missing?", chunk=_chunk("m"), best_for=None),
    ]

    passed = verification.run_search_test(drafts, user=None)

    assert [(q.text, q.search_position, q.kind) for q in passed] == [
        ("first?", 0, QuestionKind.DOCUMENT),
        ("third?", 2, QuestionKind.USER_FILE),
    ]
    assert passed[0].best_for == UseCase.HR
    assert passed[0].id != passed[1].id
    assert searches["as_user"] == []


def test_a_top_up_searches_as_the_person_with_access_built_once(
    searches: dict[str, Any],
) -> None:
    searches["results"] = {"q1?": ["a"], "q2?": ["b"]}
    alice = User(email="alice@co.com")
    drafts = [
        DraftQuestion(text="q1?", chunk=_chunk("a"), best_for=None),
        DraftQuestion(text="q2?", chunk=_chunk("b"), best_for=None),
    ]

    verification.run_search_test(drafts, user=alice)

    assert searches["as_user"] == ["alice@co.com", "alice@co.com"]
    assert searches["acl_builds"] == 1


def test_searches_run_on_a_capped_number_of_threads(
    searches: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    searches["results"] = {"q?": ["a"]}
    run = MagicMock(return_value=[0])
    monkeypatch.setattr(verification, "run_functions_tuples_in_parallel", run)

    verification.run_search_test(
        [DraftQuestion(text="q?", chunk=_chunk("a"), best_for=None)], user=None
    )

    assert run.call_args.kwargs["max_workers"] == verification.SQ_SEARCH_WORKERS


def test_a_failed_search_only_fails_its_own_question(
    searches: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    searches["results"] = {"works?": ["a"]}

    def search_everything(query: str, *_args: Any) -> list[InferenceChunk]:
        if query == "breaks?":
            raise TimeoutError("opensearch timed out")
        return [_chunk(document_id) for document_id in searches["results"][query]]

    monkeypatch.setattr(verification, "_search_everything", search_everything)
    drafts = [
        DraftQuestion(text="breaks?", chunk=_chunk("b"), best_for=None),
        DraftQuestion(text="works?", chunk=_chunk("a"), best_for=None),
    ]

    passed = verification.run_search_test(drafts, user=None)

    assert [q.text for q in passed] == ["works?"]
