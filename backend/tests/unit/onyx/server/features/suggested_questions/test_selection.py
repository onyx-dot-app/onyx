from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.db.models import User
from onyx.server.features.suggested_questions import selection
from onyx.server.features.suggested_questions.models import (
    CandidateDocument,
    QuestionKind,
    TriagedChunk,
)

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
        lambda _s, _limit, exclude, censored: [
            d
            for d in state["public"]
            if d not in exclude and censored == state["censored"]
        ],
    )
    monkeypatch.setattr(
        selection,
        "get_newest_private_document_ids",
        lambda _s, user_email, exclude_ids, censored_sources, **_kw: [
            d
            for d in state["private"].get(user_email, [])
            if d not in exclude_ids and censored_sources == state["censored"]
        ],
    )
    monkeypatch.setattr(selection, "get_user_external_group_ids", lambda *_a: [])
    state["censored"] = {DocumentSource.SALESFORCE}
    monkeypatch.setattr(
        selection, "get_censoring_enabled_sources", lambda: state["censored"]
    )
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
    alice, bob = _people(documents, "alice@co.com", "bob@co.com")

    candidates = selection.choose_documents(
        MagicMock(spec=Session), [alice, bob], set(), {}
    )

    assert candidates == [
        CandidateDocument(document_id="shared", kind=QuestionKind.DOCUMENT),
        CandidateDocument(
            document_id="alice-doc", kind=QuestionKind.DOCUMENT, owner_ids=[alice.id]
        ),
        CandidateDocument(
            document_id="alice-upload",
            kind=QuestionKind.USER_FILE,
            owner_ids=[alice.id],
        ),
        CandidateDocument(
            document_id="bob-doc", kind=QuestionKind.DOCUMENT, owner_ids=[bob.id]
        ),
    ]


def test_uploads_are_skipped_when_connector_documents_fill_the_bucket(
    documents: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "SQ_PRIVATE_DOCS_PER_USER", 1)
    alice = _people(documents, "alice@co.com")

    candidates = selection.choose_documents(MagicMock(spec=Session), alice, set(), {})

    assert [c.document_id for c in candidates] == ["shared", "alice-doc"]


def test_a_topup_uses_only_the_persons_own_documents(
    documents: dict[str, Any],
) -> None:
    alice = _people(documents, "alice@co.com")

    candidates = selection.choose_documents(
        MagicMock(spec=Session), alice, set(), {}, include_shared=False
    )

    assert [c.document_id for c in candidates] == ["alice-doc", "alice-upload"]


def test_each_shelf_skips_only_its_own_documents(
    documents: dict[str, Any],
) -> None:
    alice = _people(documents, "alice@co.com")

    candidates = selection.choose_documents(
        MagicMock(spec=Session),
        alice,
        shared_exclude_ids={"shared"},
        private_exclude_ids={alice[0].id: {"alice-upload"}},
    )

    assert [c.document_id for c in candidates] == ["alice-doc"]


def test_a_group_document_is_one_candidate_for_each_person_without_it(
    documents: dict[str, Any],
) -> None:
    documents["private"] = {"alice@co.com": ["team-doc"], "bob@co.com": ["team-doc"]}
    documents["uploads"] = {}
    alice, bob = _people(documents, "alice@co.com", "bob@co.com")
    session = MagicMock(spec=Session)

    both = selection.choose_documents(session, [alice, bob], set(), {})
    # Bob already has a question about it on his shelf.
    only_alice = selection.choose_documents(
        session, [alice, bob], set(), {bob.id: {"team-doc"}}
    )

    assert [(c.document_id, c.owner_ids) for c in both if c.owner_ids] == [
        ("team-doc", [alice.id, bob.id])
    ]
    assert [(c.document_id, c.owner_ids) for c in only_alice if c.owner_ids] == [
        ("team-doc", [alice.id])
    ]


def test_fetch_chunks_reads_the_start_of_each_document_without_acl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def leading_chunks_retrieval(filters: IndexFilters, max_chunk_index: int) -> list:
        captured["max_chunk_index"] = max_chunk_index
        captured["filters"] = filters
        return [_chunk("a"), _chunk("b", content="too short")]

    monkeypatch.setattr(selection, "SQ_FETCH_CHUNKS_PER_DOC", 4)
    index = MagicMock()
    index.leading_chunks_retrieval.side_effect = leading_chunks_retrieval
    monkeypatch.setattr(selection, "get_current_search_settings", lambda _s: None)
    monkeypatch.setattr(selection, "get_default_document_index", lambda *_a: index)
    candidates = [
        CandidateDocument(document_id="a", kind=QuestionKind.DOCUMENT),
        CandidateDocument(document_id="b", kind=QuestionKind.USER_FILE),
    ]

    chunks = selection.fetch_chunks(MagicMock(spec=Session), candidates, "tenant")

    assert [chunk.document_id for chunk in chunks] == ["a"]
    assert index.leading_chunks_retrieval.call_count == 1
    assert captured["filters"].attached_document_ids == ["a", "b"]
    assert captured["max_chunk_index"] == 3
    assert captured["filters"].access_control_list is None
    assert captured["filters"].tenant_id == "tenant"


def test_fetch_chunks_tells_an_empty_index_read_from_all_junk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = MagicMock()
    monkeypatch.setattr(selection, "get_current_search_settings", lambda _s: None)
    monkeypatch.setattr(selection, "get_default_document_index", lambda *_a: index)
    candidates = [CandidateDocument(document_id="a", kind=QuestionKind.DOCUMENT)]

    index.leading_chunks_retrieval.return_value = []
    with pytest.raises(selection.NothingSearchableYet):
        selection.fetch_chunks(MagicMock(spec=Session), candidates, "tenant")

    index.leading_chunks_retrieval.return_value = [_chunk("a", content="too short")]
    assert selection.fetch_chunks(MagicMock(spec=Session), candidates, "tenant") == []


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


def _triaged(document_id: str, usable: float, has_fact: float = 0.0) -> TriagedChunk:
    return TriagedChunk(
        chunk=_chunk(document_id, int(usable * 10)),
        usable=usable,
        sensitive=0.0,
        topic=None,
        has_fact=has_fact,
    )


def test_best_chunks_keeps_one_per_document_when_there_are_many() -> None:
    triaged = [_triaged(f"doc-{i}", 1.0) for i in range(6)] + [
        _triaged("doc-0", 3.0),
        # Rounds to the same score as doc-1's other chunk; the fact decides.
        _triaged("doc-1", 0.9, has_fact=0.9),
    ]

    best = selection.best_chunks_per_document(triaged)

    assert len(best) == 6
    assert [(item.usable, item.has_fact) for item in best[:2]] == [
        (3.0, 0.0),
        (0.9, 0.9),
    ]


def test_best_chunks_keeps_two_per_document_when_there_are_few() -> None:
    triaged = [_triaged("doc", score) for score in (1.0, 3.0, 2.0)]

    best = selection.best_chunks_per_document(triaged)

    assert [item.usable for item in best] == [3.0, 2.0]
