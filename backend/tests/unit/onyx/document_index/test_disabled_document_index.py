"""Tests for DisabledDocumentIndex — verifies all methods raise RuntimeError.

This is the safety net for the DISABLE_VECTOR_DB feature. Every method on
DisabledDocumentIndex must raise RuntimeError with the standard error message
so that any accidental vector-DB call is caught immediately.
"""

import re

import pytest

from onyx.context.search.models import IndexFilters
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.disabled import DisabledDocumentIndex
from onyx.document_index.disabled import VECTOR_DB_DISABLED_ERROR

ESCAPED_ERROR = re.escape(VECTOR_DB_DISABLED_ERROR)


@pytest.fixture
def disabled_index() -> DisabledDocumentIndex:
    return DisabledDocumentIndex(
        index_name="test_index",
        secondary_index_name="test_secondary",
    )


def _stub_filters() -> IndexFilters:
    return IndexFilters(access_control_list=None)


# ------------------------------------------------------------------
# Verifiable
# ------------------------------------------------------------------


def test_ensure_indices_exist_no_raises(
    disabled_index: DisabledDocumentIndex,
) -> None:
    disabled_index.ensure_indices_exist(
        primary_embedding_dim=768,
        primary_embedding_precision=EmbeddingPrecision.FLOAT,
        secondary_index_embedding_dim=None,
        secondary_index_embedding_precision=None,
    )


def test_register_multitenant_indices_raises() -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        DisabledDocumentIndex.register_multitenant_indices(
            indices=["idx"],
            embedding_dims=[768],
            embedding_precisions=[EmbeddingPrecision.FLOAT],
        )


# ------------------------------------------------------------------
# Indexable
# ------------------------------------------------------------------


def test_index_raises(disabled_index: DisabledDocumentIndex) -> None:
    from dataclasses import dataclass, field

    # We only need a stub — the method raises before inspecting arguments.
    @dataclass
    class _StubBatchParams:
        doc_id_to_previous_chunk_cnt: dict[str, int] = field(default_factory=dict)
        doc_id_to_new_chunk_cnt: dict[str, int] = field(default_factory=dict)
        tenant_id: str = "test"
        large_chunks_enabled: bool = False

    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.index(
            chunks=[],
            index_batch_params=_StubBatchParams(),  # type: ignore
        )


# ------------------------------------------------------------------
# Deletable
# ------------------------------------------------------------------


def test_delete_single_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.delete_single(
            doc_id="doc-1",
            tenant_id="test",
            chunk_count=None,
        )


# ------------------------------------------------------------------
# Updatable
# ------------------------------------------------------------------


def test_update_single_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.update_single(
            doc_id="doc-1",
            tenant_id="test",
            chunk_count=None,
            fields=None,
            user_fields=None,
        )


# ------------------------------------------------------------------
# IdRetrievalCapable
# ------------------------------------------------------------------


def test_id_based_retrieval_raises(
    disabled_index: DisabledDocumentIndex,
) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.id_based_retrieval(
            chunk_requests=[],
            filters=_stub_filters(),
        )


# ------------------------------------------------------------------
# HybridCapable
# ------------------------------------------------------------------


def test_hybrid_retrieval_raises(
    disabled_index: DisabledDocumentIndex,
) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.hybrid_retrieval(
            query="test",
            query_embedding=[0.0] * 768,
            final_keywords=None,
            filters=_stub_filters(),
            hybrid_alpha=0.5,
            time_decay_multiplier=1.0,
            num_to_retrieve=10,
            ranking_profile_type=QueryExpansionType.KEYWORD,
        )


# ------------------------------------------------------------------
# AdminCapable
# ------------------------------------------------------------------


def test_admin_retrieval_raises(
    disabled_index: DisabledDocumentIndex,
) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.admin_retrieval(
            query="test",
            query_embedding=[0.0] * 768,
            filters=_stub_filters(),
        )


# ------------------------------------------------------------------
# RandomCapable
# ------------------------------------------------------------------


def test_random_retrieval_raises(
    disabled_index: DisabledDocumentIndex,
) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.random_retrieval(
            filters=_stub_filters(),
        )


# ------------------------------------------------------------------
# Introspection — index_name and secondary_index_name should still work
# ------------------------------------------------------------------


def test_index_names_accessible(disabled_index: DisabledDocumentIndex) -> None:
    assert disabled_index.index_name == "test_index"
    assert disabled_index.secondary_index_name == "test_secondary"


def test_default_names() -> None:
    index = DisabledDocumentIndex()
    assert index.index_name == "disabled"
    assert index.secondary_index_name is None
