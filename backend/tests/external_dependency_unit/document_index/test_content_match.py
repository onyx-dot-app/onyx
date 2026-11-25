"""External dependency tests for matching documents by content.

Content matching lists or counts every document with a chunk that contains a
phrase, each document once, in date order, and applies the same permission and
hidden filters as search.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from onyx.access.models import DocumentAccess
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.context.search.models import IndexFilters
from onyx.document_index.interfaces import (
    ContentMatchCount,
    ContentMatchDateField,
    ContentMatchKey,
    ContentMatchRequest,
    MetadataUpdateRequest,
)
from onyx.document_index.opensearch import opensearch_document_index
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    make_chunk,
    make_indexing_metadata,
)

_ALICE = "alice@example.com"
_PUBLIC_ACCESS = DocumentAccess.build(
    user_emails=[],
    user_groups=[],
    external_user_emails=[],
    external_user_group_ids=[],
    is_public=True,
)
_ALICE_ACCESS = DocumentAccess.build(
    user_emails=[_ALICE],
    user_groups=[],
    external_user_emails=[],
    external_user_group_ids=[],
    is_public=False,
)


def _day(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


# (document ID, updated date, access, chunk contents)
_DOCUMENTS: list[tuple[str, datetime | None, DocumentAccess, list[str]]] = [
    ("d1", _day(5), _PUBLIC_ACCESS, ["the quick brown fox", "lorem ipsum"]),
    # The words, but not as the phrase.
    ("d2", _day(3), _PUBLIC_ACCESS, ["brown and quick fox"]),
    ("d3", _day(4), _ALICE_ACCESS, ["a quick brown dog"]),
    # Hidden after indexing.
    ("d4", _day(7), _PUBLIC_ACCESS, ["a quick brown cat"]),
    ("d5", None, _PUBLIC_ACCESS, ["a quick brown bird"]),
    # Matches in its second chunk, after case folding and stemming.
    ("d6", _day(1), _PUBLIC_ACCESS, ["nothing here", "Quick Browns jumping"]),
    ("d7", _day(2), _PUBLIC_ACCESS, ["zebra crossing"]),
    # Same date: the document ID breaks the tie.
    ("d8", _day(6), _PUBLIC_ACCESS, ["tie breaker"]),
    ("d9", _day(6), _PUBLIC_ACCESS, ["tie breaker"]),
]


def _chunks() -> list[DocMetadataAwareIndexChunk]:
    chunks = []
    for doc_id, updated_at, access, contents in _DOCUMENTS:
        for chunk_id, content in enumerate(contents):
            chunk = make_chunk(doc_id, chunk_id=chunk_id, content=content)
            chunks.append(
                chunk.model_copy(
                    update={
                        "access": access,
                        "source_document": chunk.source_document.model_copy(
                            update={"doc_updated_at": updated_at}
                        ),
                    }
                )
            )
    return chunks


@pytest.fixture(scope="module")
def content_index(
    opensearch_index: OpenSearchDocumentIndex,
) -> Generator[OpenSearchDocumentIndex, None, None]:
    chunks = _chunks()
    doc_ids = [doc_id for doc_id, *_ in _DOCUMENTS]
    chunk_counts = [len(contents) for *_, contents in _DOCUMENTS]
    opensearch_index.index(
        chunks, make_indexing_metadata(doc_ids, [0] * len(doc_ids), chunk_counts)
    )
    opensearch_index.update(
        [
            MetadataUpdateRequest(
                document_ids=["d4"], doc_id_to_chunk_cnt={"d4": 1}, hidden=True
            )
        ]
    )
    opensearch_index._client.refresh_index()
    yield opensearch_index


def _request(
    phrases: list[str],
    acl: list[str] | None = None,
    document_ids: list[str] | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
) -> ContentMatchRequest:
    return ContentMatchRequest(
        phrases=phrases,
        filters=IndexFilters(
            access_control_list=acl or [PUBLIC_DOC_PAT],
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        ),
        document_ids=document_ids,
        updated_after=updated_after,
        updated_before=updated_before,
    )


def _match_ids(
    index: OpenSearchDocumentIndex,
    request: ContentMatchRequest,
    descending: bool = True,
    page_size: int = 100,
) -> list[str]:
    """Pages through every match and returns the document IDs in order."""
    doc_ids: list[str] = []
    after: ContentMatchKey | None = None
    while True:
        page = index.match_documents_by_content(
            request, ContentMatchDateField.UPDATED, descending, after, page_size
        )
        doc_ids.extend(key.document_id for key in page)
        if len(page) < page_size:
            return doc_ids
        after = page[-1]


def test_lists_phrase_matches_newest_first_with_undated_last(
    content_index: OpenSearchDocumentIndex,
) -> None:
    assert _match_ids(content_index, _request(["quick brown"])) == ["d1", "d6", "d5"]


def test_lists_oldest_first_with_undated_still_last(
    content_index: OpenSearchDocumentIndex,
) -> None:
    assert _match_ids(content_index, _request(["quick brown"]), descending=False) == [
        "d6",
        "d1",
        "d5",
    ]


def test_returns_each_match_with_its_date(
    content_index: OpenSearchDocumentIndex,
) -> None:
    page = content_index.match_documents_by_content(
        _request(["quick brown"]), ContentMatchDateField.UPDATED, True, None, 10
    )
    assert page == [
        ContentMatchKey(document_id="d1", date=_day(5)),
        ContentMatchKey(document_id="d6", date=_day(1)),
        ContentMatchKey(document_id="d5", date=None),
    ]


def test_permissions_decide_which_documents_match(
    content_index: OpenSearchDocumentIndex,
) -> None:
    alice_acl = [PUBLIC_DOC_PAT, prefix_user_email(_ALICE)]
    assert _match_ids(content_index, _request(["quick brown"], acl=alice_acl)) == [
        "d1",
        "d3",
        "d6",
        "d5",
    ]


def test_any_phrase_matches(content_index: OpenSearchDocumentIndex) -> None:
    assert _match_ids(content_index, _request(["quick brown", "zebra"])) == [
        "d1",
        "d7",
        "d6",
        "d5",
    ]


def test_document_ids_narrow_the_matches(
    content_index: OpenSearchDocumentIndex,
) -> None:
    request = _request(["quick brown"], document_ids=["d2", "d5", "d6"])
    assert _match_ids(content_index, request) == ["d6", "d5"]


def test_updated_window_is_strict(content_index: OpenSearchDocumentIndex) -> None:
    request = _request(["quick brown"], updated_after=_day(1), updated_before=_day(5))
    # d1 is updated exactly at the exclusive end, d5 has no date.
    assert _match_ids(content_index, request) == ["d6"]
    request = _request(["quick brown"], updated_after=_day(2))
    assert _match_ids(content_index, request) == ["d1"]


def test_updated_window_keeps_the_boundary_second(
    content_index: OpenSearchDocumentIndex,
) -> None:
    # The index stores whole seconds, so both bounds admit their boundary
    # second: d1 is before the fractional end, and d6 is in the start's second.
    request = _request(
        ["quick brown"],
        updated_after=_day(1) + timedelta(milliseconds=500),
        updated_before=_day(5) + timedelta(milliseconds=500),
    )
    assert _match_ids(content_index, request) == ["d1", "d6"]


@pytest.mark.parametrize("descending", [True, False])
def test_single_document_pages_match_one_page(
    content_index: OpenSearchDocumentIndex, descending: bool
) -> None:
    request = _request(["quick brown", "tie breaker", "zebra"])
    whole = _match_ids(content_index, request, descending=descending)
    assert len(whole) == 6
    assert _match_ids(content_index, request, descending, page_size=1) == whole


def test_same_date_orders_by_document_id(
    content_index: OpenSearchDocumentIndex,
) -> None:
    request = _request(["tie breaker"])
    assert _match_ids(content_index, request, page_size=1) == ["d9", "d8"]
    assert _match_ids(content_index, request, descending=False, page_size=1) == [
        "d8",
        "d9",
    ]


def test_counts_distinct_documents(content_index: OpenSearchDocumentIndex) -> None:
    request = _request(["quick brown", "lorem", "nothing"])
    assert content_index.count_documents_by_content(
        request, max_count=100
    ) == ContentMatchCount(count=3, is_complete=True)


def test_counts_across_pages_and_stops_at_the_limit(
    content_index: OpenSearchDocumentIndex,
) -> None:
    request = _request(["quick brown", "tie breaker", "zebra"])
    with patch.object(opensearch_document_index, "_CONTENT_COUNT_PAGE_SIZE", 2):
        assert content_index.count_documents_by_content(
            request, max_count=100
        ) == ContentMatchCount(count=6, is_complete=True)
        assert content_index.count_documents_by_content(
            request, max_count=3
        ) == ContentMatchCount(count=4, is_complete=False)


def test_count_stops_at_the_deadline(
    content_index: OpenSearchDocumentIndex,
) -> None:
    request = _request(["quick brown", "tie breaker", "zebra"])
    with patch.object(opensearch_document_index, "_CONTENT_COUNT_PAGE_SIZE", 2):
        assert content_index.count_documents_by_content(
            request, max_count=100, deadline=0.0
        ) == ContentMatchCount(count=2, is_complete=False)


def test_shard_failures_are_errors(content_index: OpenSearchDocumentIndex) -> None:
    partial = {
        "took": 1,
        "timed_out": False,
        "_shards": {"total": 3, "successful": 2, "failed": 1},
        "hits": {"hits": []},
        "aggregations": {"document_ids": {"buckets": []}},
    }
    request = _request(["quick brown"])
    with patch.object(content_index._client._client, "search", return_value=partial):
        with pytest.raises(RuntimeError, match="shard failures"):
            content_index.match_documents_by_content(
                request, ContentMatchDateField.UPDATED, True, None, 10
            )
        with pytest.raises(RuntimeError, match="shard failures"):
            content_index.count_documents_by_content(request, max_count=100)
