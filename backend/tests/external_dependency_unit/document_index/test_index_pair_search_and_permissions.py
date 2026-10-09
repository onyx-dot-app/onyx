"""External dependency tests for the search and permission paths of the
document index returned by `get_default_document_index`.

Every write and read goes through an `OpenSearchIndexPair`: one primary index
and, during a re-index, one secondary index. These tests run against a real
OpenSearch and check that:
- metadata updates (access, document sets, hidden) reach both indices and that
  retrieval enforces them,
- deletes reach both indices, and writes and reads use the primary only,
- search-result expansion finds the neighbors of documents whose IDs contain
  characters the former Vespa backend rewrote (for example `'`).

These tests assume OpenSearch is running.
"""

import time
import uuid
from collections.abc import Callable, Generator
from typing import TypeVar
from unittest.mock import MagicMock

import pytest

from onyx.access.models import DocumentAccess
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.context.search.models import IndexFilters, InferenceChunk, InferenceSection
from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import (
    DocumentSectionRequest,
    MetadataUpdateRequest,
    TenantState,
)
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
    OpenSearchIndexPair,
)
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.tools.tool_implementations.search.search_utils import (
    _retrieve_adjacent_chunks,
    expand_section_with_context,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

T = TypeVar("T")

TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
OWNER = "owner@example.com"
OTHER_USER = "other@example.com"


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------


def _wait_for(
    read: Callable[[], T], done: Callable[[T], bool], timeout_s: float = 10.0
) -> T:
    """Polls `read` until `done` holds. OpenSearch makes writes visible to
    search only after a refresh."""
    deadline = time.monotonic() + timeout_s
    value = read()
    while not done(value) and time.monotonic() < deadline:
        time.sleep(0.25)
        value = read()
    return value


def _filters(acl: list[str], document_sets: list[str] | None = None) -> IndexFilters:
    return IndexFilters(
        access_control_list=acl,
        document_set=document_sets,
        tenant_id=TENANT_ID,
    )


def _owner_filters(document_sets: list[str] | None = None) -> IndexFilters:
    return _filters([PUBLIC_DOC_PAT, prefix_user_email(OWNER)], document_sets)


def _other_user_filters() -> IndexFilters:
    return _filters([PUBLIC_DOC_PAT, prefix_user_email(OTHER_USER)])


def _private_access(user_email: str) -> DocumentAccess:
    return DocumentAccess.build(
        user_emails=[user_email],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=False,
    )


def _chunks(
    doc_id: str, count: int, access: DocumentAccess | None = None
) -> list[DocMetadataAwareIndexChunk]:
    chunks = []
    for chunk_id in range(count):
        chunk = make_chunk(
            doc_id,
            chunk_id=chunk_id,
            content=f"quarterly zebra roadmap part {chunk_id}",
        )
        if access is not None:
            chunk.access = access
        chunks.append(chunk)
    return chunks


def _index(
    document_index: OpenSearchDocumentIndex | OpenSearchIndexPair,
    chunks: list[DocMetadataAwareIndexChunk],
) -> None:
    doc_id = chunks[0].source_document.id
    document_index.index(
        chunks=chunks,
        indexing_metadata=make_indexing_metadata(
            [doc_id], old_counts=[0], new_counts=[len(chunks)]
        ),
    )


def _chunk_ids(
    document_index: OpenSearchDocumentIndex | OpenSearchIndexPair,
    doc_id: str,
    filters: IndexFilters,
) -> list[int]:
    chunks = document_index.id_based_retrieval(
        chunk_requests=[DocumentSectionRequest(document_id=doc_id)],
        filters=filters,
        batch_retrieval=True,
    )
    return sorted(chunk.chunk_id for chunk in chunks)


def _wait_for_chunk_ids(
    document_index: OpenSearchDocumentIndex | OpenSearchIndexPair,
    doc_id: str,
    filters: IndexFilters,
    expected: list[int],
) -> list[int]:
    return _wait_for(
        lambda: _chunk_ids(document_index, doc_id, filters),
        lambda ids: ids == expected,
    )


def _new_index(name: str) -> OpenSearchDocumentIndex:
    document_index = OpenSearchDocumentIndex(
        tenant_state=TenantState(tenant_id=TENANT_ID, multitenant=False),
        index_name=name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    document_index.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    return document_index


# ------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def primary_and_secondary(
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[OpenSearchDocumentIndex, OpenSearchDocumentIndex], None, None]:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    suffix = uuid.uuid4().hex[:8]
    names = [f"test_pair_primary_{suffix}", f"test_pair_secondary_{suffix}"]
    primary, secondary = (_new_index(name) for name in names)
    try:
        yield primary, secondary
    finally:
        for name in names:
            OpenSearchIndexClient(index_name=name).delete_index()


@pytest.fixture(scope="module")
def pair(
    primary_and_secondary: tuple[OpenSearchDocumentIndex, OpenSearchDocumentIndex],
) -> OpenSearchIndexPair:
    primary, secondary = primary_and_secondary
    return OpenSearchIndexPair(
        primary=primary,
        secondary=secondary,
        secondary_embedding_dim=EMBEDDING_DIM,
    )


@pytest.fixture(scope="module")
def primary(
    primary_and_secondary: tuple[OpenSearchDocumentIndex, OpenSearchDocumentIndex],
) -> OpenSearchDocumentIndex:
    return primary_and_secondary[0]


@pytest.fixture(scope="module")
def secondary(
    primary_and_secondary: tuple[OpenSearchDocumentIndex, OpenSearchDocumentIndex],
) -> OpenSearchDocumentIndex:
    return primary_and_secondary[1]


def _doc_id(label: str) -> str:
    return f"{label}_{uuid.uuid4().hex[:8]}"


def _index_in_both(
    pair: OpenSearchIndexPair,
    secondary: OpenSearchDocumentIndex,
    chunks: list[DocMetadataAwareIndexChunk],
) -> None:
    """Writes go to the primary only; a re-index fills the secondary on its own,
    which is what the direct secondary write stands in for."""
    _index(pair, chunks)
    _index(secondary, chunks)


# ------------------------------------------------------------------------------
# Writes and reads
# ------------------------------------------------------------------------------


class TestPairRouting:
    def test_index_writes_the_primary_only(
        self,
        pair: OpenSearchIndexPair,
        primary: OpenSearchDocumentIndex,
        secondary: OpenSearchDocumentIndex,
    ) -> None:
        doc_id = _doc_id("routing_index")
        _index(pair, _chunks(doc_id, 2))

        assert _wait_for_chunk_ids(primary, doc_id, _owner_filters(), [0, 1]) == [
            0,
            1,
        ]
        assert _chunk_ids(secondary, doc_id, _owner_filters()) == []

    def test_retrieval_reads_the_primary_only(
        self,
        pair: OpenSearchIndexPair,
        secondary: OpenSearchDocumentIndex,
    ) -> None:
        doc_id = _doc_id("routing_read")
        _index(secondary, _chunks(doc_id, 2))
        _wait_for_chunk_ids(secondary, doc_id, _owner_filters(), [0, 1])

        assert _chunk_ids(pair, doc_id, _owner_filters()) == []

    def test_delete_removes_the_document_from_both_indices(
        self,
        pair: OpenSearchIndexPair,
        primary: OpenSearchDocumentIndex,
        secondary: OpenSearchDocumentIndex,
    ) -> None:
        doc_id = _doc_id("routing_delete")
        _index_in_both(pair, secondary, _chunks(doc_id, 3))
        _wait_for_chunk_ids(primary, doc_id, _owner_filters(), [0, 1, 2])
        _wait_for_chunk_ids(secondary, doc_id, _owner_filters(), [0, 1, 2])

        deleted = pair.delete(doc_id, chunk_count=3)

        assert deleted == 6
        for document_index in (primary, secondary):
            assert (
                _wait_for_chunk_ids(document_index, doc_id, _owner_filters(), []) == []
            )


# ------------------------------------------------------------------------------
# Permission and metadata updates
# ------------------------------------------------------------------------------


class TestPairMetadataUpdates:
    def test_access_update_reaches_both_indices_and_is_enforced(
        self,
        pair: OpenSearchIndexPair,
        primary: OpenSearchDocumentIndex,
        secondary: OpenSearchDocumentIndex,
    ) -> None:
        """Moving a document from one user to another must revoke the first
        user's access and grant the second user access in both indices."""
        doc_id = _doc_id("acl_move")
        _index_in_both(pair, secondary, _chunks(doc_id, 2, _private_access(OWNER)))
        for document_index in (primary, secondary):
            _wait_for_chunk_ids(document_index, doc_id, _owner_filters(), [0, 1])
            assert _chunk_ids(document_index, doc_id, _other_user_filters()) == []

        pair.update(
            [
                MetadataUpdateRequest(
                    document_ids=[doc_id],
                    doc_id_to_chunk_cnt={doc_id: 2},
                    access=_private_access(OTHER_USER),
                )
            ]
        )

        for document_index in (primary, secondary):
            assert (
                _wait_for_chunk_ids(document_index, doc_id, _owner_filters(), []) == []
            )
            assert _wait_for_chunk_ids(
                document_index, doc_id, _other_user_filters(), [0, 1]
            ) == [0, 1]

    def test_access_update_is_enforced_by_keyword_search(
        self,
        pair: OpenSearchIndexPair,
        secondary: OpenSearchDocumentIndex,
    ) -> None:
        doc_id = _doc_id("acl_keyword")
        _index_in_both(pair, secondary, _chunks(doc_id, 1, _private_access(OWNER)))

        def _hit_ids(filters: IndexFilters) -> set[str]:
            chunks: list[InferenceChunk] = pair.keyword_retrieval(
                query="quarterly zebra roadmap",
                filters=filters,
                num_to_retrieve=50,
            )
            return {chunk.document_id for chunk in chunks}

        assert doc_id in _wait_for(
            lambda: _hit_ids(_owner_filters()), lambda ids: doc_id in ids
        )
        assert doc_id not in _hit_ids(_other_user_filters())

        pair.update(
            [
                MetadataUpdateRequest(
                    document_ids=[doc_id],
                    doc_id_to_chunk_cnt={doc_id: 1},
                    access=_private_access(OTHER_USER),
                )
            ]
        )

        assert doc_id in _wait_for(
            lambda: _hit_ids(_other_user_filters()), lambda ids: doc_id in ids
        )
        assert doc_id not in _wait_for(
            lambda: _hit_ids(_owner_filters()), lambda ids: doc_id not in ids
        )

    def test_document_set_update_reaches_both_indices(
        self,
        pair: OpenSearchIndexPair,
        primary: OpenSearchDocumentIndex,
        secondary: OpenSearchDocumentIndex,
    ) -> None:
        doc_id = _doc_id("doc_set")
        _index_in_both(pair, secondary, _chunks(doc_id, 2))
        engineering = _owner_filters(document_sets=["Engineering"])
        for document_index in (primary, secondary):
            _wait_for_chunk_ids(document_index, doc_id, _owner_filters(), [0, 1])
            assert _chunk_ids(document_index, doc_id, engineering) == []

        pair.update(
            [
                MetadataUpdateRequest(
                    document_ids=[doc_id],
                    doc_id_to_chunk_cnt={doc_id: 2},
                    document_sets={"Engineering"},
                )
            ]
        )

        legal = _owner_filters(document_sets=["Legal"])
        for document_index in (primary, secondary):
            assert _wait_for_chunk_ids(document_index, doc_id, engineering, [0, 1]) == [
                0,
                1,
            ]
            assert _chunk_ids(document_index, doc_id, legal) == []

    def test_hidden_update_reaches_both_indices(
        self,
        pair: OpenSearchIndexPair,
        primary: OpenSearchDocumentIndex,
        secondary: OpenSearchDocumentIndex,
    ) -> None:
        doc_id = _doc_id("hidden")
        _index_in_both(pair, secondary, _chunks(doc_id, 2))
        for document_index in (primary, secondary):
            _wait_for_chunk_ids(document_index, doc_id, _owner_filters(), [0, 1])

        pair.update(
            [
                MetadataUpdateRequest(
                    document_ids=[doc_id],
                    doc_id_to_chunk_cnt={doc_id: 2},
                    hidden=True,
                )
            ]
        )

        for document_index in (primary, secondary):
            assert (
                _wait_for_chunk_ids(document_index, doc_id, _owner_filters(), []) == []
            )


# ------------------------------------------------------------------------------
# Search-result expansion
# ------------------------------------------------------------------------------


class TestSectionExpansion:
    @pytest.mark.parametrize(
        "doc_id",
        [
            "plain_document",
            "https://example.com/o'brien's notes?page=1",
        ],
    )
    def test_expansion_finds_neighbors(
        self,
        pair: OpenSearchIndexPair,
        doc_id: str,
    ) -> None:
        doc_id = f"{doc_id}#{uuid.uuid4().hex[:8]}"
        _index(pair, _chunks(doc_id, 6))
        _wait_for_chunk_ids(pair, doc_id, _owner_filters(), list(range(6)))
        (center,) = pair.id_based_retrieval(
            chunk_requests=[
                DocumentSectionRequest(
                    document_id=doc_id, min_chunk_ind=2, max_chunk_ind=2
                )
            ],
            filters=_owner_filters(),
            batch_retrieval=True,
        )
        section = InferenceSection(
            center_chunk=center, chunks=[center], combined_content=center.content
        )

        above, below = _retrieve_adjacent_chunks(
            section=section,
            document_index=pair,
            num_chunks_above=2,
            num_chunks_below=2,
        )
        assert [chunk.chunk_id for chunk in above] == [0, 1]
        assert [chunk.chunk_id for chunk in below] == [3, 4]

        llm = MagicMock()
        expanded = expand_section_with_context(
            section=section,
            user_query="roadmap",
            llm=llm,
            document_index=pair,
            expand_override=True,
        )
        assert expanded is not None
        assert [chunk.chunk_id for chunk in expanded.chunks] == list(range(6))
        llm.invoke.assert_not_called()
