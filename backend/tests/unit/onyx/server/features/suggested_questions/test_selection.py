from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.db.models import User
from onyx.server.features.suggested_questions import selection
from onyx.server.features.suggested_questions.models import QuestionKind
from onyx.server.features.suggested_questions.selection import CandidateDocument

PROSE = (
    "Employees may work from another country for up to thirty working days in "
    "each calendar year. Requests longer than ten days in a row need approval "
    "from People Operations through the travel form, at least two weeks before "
    "the trip starts. The manager confirms coverage for the team while away. "
    "Tax rules differ by country, so check the guide before booking travel. "
)


def _chunk(document_id: str, chunk_id: int = 0, content: str = PROSE) -> InferenceChunk:
    return InferenceChunk(
        document_id=document_id,
        chunk_id=chunk_id,
        content=content,
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


def _user(email: str) -> User:
    return User(id=uuid4(), email=email)


@pytest.fixture
def documents(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A shared connector document, one only Alice can see, one only Bob can
    see; Alice also uploaded a file."""
    state: dict[str, Any] = {
        "public": ["shared"],
        "private": {"alice@co.com": ["alice-doc"], "bob@co.com": ["bob-doc"]},
        "uploads": {"alice@co.com": ["alice-upload"]},
    }
    monkeypatch.setattr(
        selection,
        "get_newest_public_document_ids",
        lambda _s, _limit, exclude: [d for d in state["public"] if d not in exclude],
    )
    monkeypatch.setattr(
        selection,
        "get_newest_private_document_ids",
        lambda _s, user_email, exclude_ids, **_kw: [
            d for d in state["private"].get(user_email, []) if d not in exclude_ids
        ],
    )
    monkeypatch.setattr(selection, "get_user_external_group_ids", lambda *_a: [])
    emails_by_id: dict[Any, str] = {}
    state["emails_by_id"] = emails_by_id
    monkeypatch.setattr(
        selection,
        "get_recent_user_file_ids",
        lambda _s, user_id, _limit, exclude: [
            f
            for f in state["uploads"].get(emails_by_id[user_id], [])
            if f not in exclude
        ],
    )
    return state


def _people(state: dict[str, Any], *emails: str) -> list[User]:
    people = [_user(email) for email in emails]
    for person in people:
        state["emails_by_id"][person.id] = person.email
    return people


def test_shared_first_then_each_persons_private_documents(
    documents: dict[str, Any],
) -> None:
    people = _people(documents, "alice@co.com", "bob@co.com")

    candidates = selection.choose_documents(MagicMock(spec=Session), people, set())

    assert candidates == [
        CandidateDocument(document_id="shared", kind=QuestionKind.DOCUMENT),
        CandidateDocument(document_id="alice-doc", kind=QuestionKind.DOCUMENT),
        CandidateDocument(document_id="alice-upload", kind=QuestionKind.USER_FILE),
        CandidateDocument(document_id="bob-doc", kind=QuestionKind.DOCUMENT),
    ]


def test_uploads_are_skipped_when_connector_documents_fill_the_bucket(
    documents: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "SQ_PRIVATE_DOCS_PER_USER", 1)
    alice = _people(documents, "alice@co.com")

    candidates = selection.choose_documents(MagicMock(spec=Session), alice, set())

    assert [c.document_id for c in candidates] == ["shared", "alice-doc"]


def test_topup_prefers_the_persons_private_documents(
    documents: dict[str, Any],
) -> None:
    alice = _people(documents, "alice@co.com")

    candidates = selection.choose_documents(
        MagicMock(spec=Session), alice, set(), prefer_private=True
    )

    assert [c.document_id for c in candidates] == [
        "alice-doc",
        "alice-upload",
        "shared",
    ]


def test_documents_already_in_the_pool_are_skipped(
    documents: dict[str, Any],
) -> None:
    alice = _people(documents, "alice@co.com")

    candidates = selection.choose_documents(
        MagicMock(spec=Session), alice, {"shared", "alice-upload"}
    )

    assert [c.document_id for c in candidates] == ["alice-doc"]


def test_fetch_chunks_asks_the_index_for_the_chosen_documents_without_acl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def random_retrieval(filters: IndexFilters, num_to_retrieve: int) -> list:
        captured["filters"] = filters
        captured["num_to_retrieve"] = num_to_retrieve
        return [_chunk("a"), _chunk("b", content="too short")]

    index = MagicMock()
    index.random_retrieval.side_effect = random_retrieval
    monkeypatch.setattr(selection, "get_current_search_settings", lambda _s: None)
    monkeypatch.setattr(selection, "get_default_document_index", lambda *_a: index)
    candidates = [
        CandidateDocument(document_id="a", kind=QuestionKind.DOCUMENT),
        CandidateDocument(document_id="b", kind=QuestionKind.USER_FILE),
    ]

    chunks = selection.fetch_chunks(MagicMock(spec=Session), candidates, "tenant")

    assert [chunk.document_id for chunk in chunks] == ["a"]
    assert captured["filters"].attached_document_ids == ["a", "b"]
    assert captured["filters"].access_control_list is None
    assert captured["filters"].tenant_id == "tenant"
    assert captured["num_to_retrieve"] == 12


def test_keep_useful_chunks_caps_per_document_and_prefers_early_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selection, "SQ_CHUNKS_PER_DOC", 2)
    # Distinct words per chunk, so the overlap rule keeps all of them.
    chunks = [
        _chunk("doc", chunk_id, " ".join(f"{word}{i}" for i in range(80)))
        for chunk_id, word in [(5, "alpha"), (0, "beta"), (3, "gamma")]
    ]

    kept = selection.keep_useful_chunks(chunks)

    assert [chunk.chunk_id for chunk in kept] == [0, 3]


def test_keep_useful_chunks_drops_near_duplicates() -> None:
    kept = selection.keep_useful_chunks([_chunk("a"), _chunk("b")])
    assert [chunk.document_id for chunk in kept] == ["a"]


@pytest.mark.parametrize(
    "content, useful",
    [
        (PROSE, True),
        ("Too short to ask anything about.", False),
        ("12,400 | 3.2% | 98 | 1,204 | 77 | " * 20, False),
        (" ".join(["https://example.com/page"] * 40) + " " + PROSE[:200], False),
        ("Confidential - do not share\n" * 6 + PROSE, False),
    ],
)
def test_looks_useful(content: str, useful: bool) -> None:
    assert selection.looks_useful(content) is useful
