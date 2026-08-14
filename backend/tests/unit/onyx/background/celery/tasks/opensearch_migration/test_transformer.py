"""Unit tests for the OpenSearch migration transformer.

These tests require no external services — all interactions with Vespa and
OpenSearch are bypassed by calling the pure transformation functions directly.
"""

import pytest

from onyx.background.celery.tasks.opensearch_migration.transformer import (
    _MAX_LUCENE_TERM_BYTES,
    _truncate_metadata_list,
    transform_vespa_chunks_to_opensearch_chunks,
)
from onyx.document_index.interfaces_new import TenantState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_EMBEDDING_DIM = 4
_DUMMY_VECTOR = [0.1, 0.2, 0.3, 0.4]


def _make_vespa_chunk(
    document_id: str = "doc-1",
    chunk_id: int = 0,
    metadata_list: list[str] | None = None,
) -> dict:
    """Return a minimal valid Vespa chunk dict for use in transformer tests."""
    return {
        "document_id": document_id,
        "chunk_id": chunk_id,
        "title": "Test Document",
        "title_embedding": _DUMMY_VECTOR,
        "content": "Some content",
        "embeddings": {"full_chunk": _DUMMY_VECTOR},
        "source_type": "web",
        "metadata_list": metadata_list,
        "doc_updated_at": None,
        "hidden": False,
        "boost": 0,
        "semantic_identifier": "test-doc",
        "image_file_name": None,
        "source_links": None,
        "blurb": "",
        "doc_summary": "",
        "chunk_context": "",
        "metadata_suffix": None,
        "document_sets": None,
        "user_project": None,
        "personas": None,
        "primary_owners": None,
        "secondary_owners": None,
        "access_control_list": {"PUBLIC": 1},
    }


def _tenant_state() -> TenantState:
    return TenantState(tenant_id="test-tenant", multitenant=False)


# ---------------------------------------------------------------------------
# _truncate_metadata_list
# ---------------------------------------------------------------------------


class TestTruncateMetadataList:
    def test_short_items_unchanged(self) -> None:
        items = ["hello", "world", "a" * 100]
        assert _truncate_metadata_list(items) == items

    def test_empty_list(self) -> None:
        assert _truncate_metadata_list([]) == []

    def test_exactly_at_limit_unchanged(self) -> None:
        item = "a" * _MAX_LUCENE_TERM_BYTES
        result = _truncate_metadata_list([item])
        assert len(result) == 1
        assert len(result[0].encode("utf-8")) == _MAX_LUCENE_TERM_BYTES

    def test_one_byte_over_limit_truncated(self) -> None:
        item = "a" * (_MAX_LUCENE_TERM_BYTES + 1)
        result = _truncate_metadata_list([item])
        assert len(result) == 1
        encoded = result[0].encode("utf-8")
        assert len(encoded) <= _MAX_LUCENE_TERM_BYTES

    def test_very_large_item_truncated(self) -> None:
        # Simulate a ~1.6 MB draw.io XML blob as seen in the bug report.
        large_item = "x" * 1_639_635
        result = _truncate_metadata_list([large_item])
        assert len(result) == 1
        encoded = result[0].encode("utf-8")
        assert len(encoded) <= _MAX_LUCENE_TERM_BYTES

    def test_mixed_short_and_large_items(self) -> None:
        short = "hello"
        large = "y" * (_MAX_LUCENE_TERM_BYTES * 2)
        result = _truncate_metadata_list([short, large])
        assert result[0] == short
        assert len(result[1].encode("utf-8")) <= _MAX_LUCENE_TERM_BYTES

    def test_multibyte_truncation_produces_valid_utf8(self) -> None:
        # Build a string of 3-byte UTF-8 characters (U+4E2D = '中').
        # Each character is 3 bytes, so we need enough to exceed the limit.
        char = "中"
        assert len(char.encode("utf-8")) == 3
        # 32_766 / 3 = 10_922 characters exactly at the limit.
        # Add one more character to exceed it.
        item = char * (10_922 + 1)
        assert len(item.encode("utf-8")) > _MAX_LUCENE_TERM_BYTES

        result = _truncate_metadata_list([item])
        encoded = result[0].encode("utf-8")

        # Must not exceed the limit.
        assert len(encoded) <= _MAX_LUCENE_TERM_BYTES
        # Must decode without errors (errors="ignore" drops incomplete bytes).
        assert encoded.decode("utf-8")


# ---------------------------------------------------------------------------
# transform_vespa_chunks_to_opensearch_chunks — metadata_list integration
# ---------------------------------------------------------------------------


class TestTransformVespaChunksMetadataList:
    def test_normal_metadata_list_preserved(self) -> None:
        chunk = _make_vespa_chunk(metadata_list=["Subject===hello", "Author===world"])
        results, errors = transform_vespa_chunks_to_opensearch_chunks(
            [chunk], _tenant_state(), {}
        )
        assert len(errors) == 0
        assert len(results) == 1
        assert results[0].metadata_list == ["Subject===hello", "Author===world"]

    def test_none_metadata_list_preserved(self) -> None:
        chunk = _make_vespa_chunk(metadata_list=None)
        results, errors = transform_vespa_chunks_to_opensearch_chunks(
            [chunk], _tenant_state(), {}
        )
        assert len(errors) == 0
        assert len(results) == 1
        assert results[0].metadata_list is None

    def test_oversized_metadata_list_item_does_not_raise(self) -> None:
        """Regression test for #10459.

        A chunk whose metadata_list contains a term larger than 32,766 bytes
        must be transformed successfully without raising, so the migration
        never stalls on such a chunk.
        """
        large_value = "Subject===" + ("x" * 1_639_635)
        chunk = _make_vespa_chunk(metadata_list=[large_value, "Author===alice"])

        # Must not raise.
        results, errors = transform_vespa_chunks_to_opensearch_chunks(
            [chunk], _tenant_state(), {}
        )

        assert len(errors) == 0, f"Expected 0 errors, got: {errors}"
        assert len(results) == 1

        # Every item in the result must be within the Lucene limit.
        for item in results[0].metadata_list or []:
            assert len(item.encode("utf-8")) <= _MAX_LUCENE_TERM_BYTES, (
                f"metadata_list item still exceeds Lucene limit after truncation: "
                f"{len(item.encode('utf-8'))} bytes"
            )

    def test_oversized_item_alongside_normal_items(self) -> None:
        items = [
            "normal-item",
            "z" * (_MAX_LUCENE_TERM_BYTES + 5_000),
            "another-normal",
        ]
        chunk = _make_vespa_chunk(metadata_list=items)
        results, errors = transform_vespa_chunks_to_opensearch_chunks(
            [chunk], _tenant_state(), {}
        )
        assert len(errors) == 0
        assert len(results) == 1
        result_list = results[0].metadata_list or []
        assert result_list[0] == "normal-item"
        assert result_list[2] == "another-normal"
        for item in result_list:
            assert len(item.encode("utf-8")) <= _MAX_LUCENE_TERM_BYTES
