"""Unit tests for DocumentChunk datetime (de)serialization.

`created_at` and `last_updated` are stored in OpenSearch as epoch seconds. These
pin that the pydantic model serializes tz-aware datetimes to epoch ints, parses
them back to UTC datetimes, and omits the fields entirely when unset.
"""

from datetime import datetime
from datetime import timezone

from onyx.document_index.opensearch.schema import CREATED_AT_FIELD_NAME
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors
from onyx.document_index.opensearch.schema import LAST_UPDATED_FIELD_NAME


def _make_chunk(
    created_at: datetime | None,
    last_updated: datetime | None,
) -> DocumentChunkWithoutVectors:
    return DocumentChunkWithoutVectors(
        document_id="doc-1",
        chunk_index=0,
        content="hello",
        source_type="web",
        created_at=created_at,
        last_updated=last_updated,
        public=True,
        access_control_list=[],
        global_boost=0,
        semantic_identifier="doc-1",
        blurb="hello",
        doc_summary="",
        chunk_context="",
    )


def test_created_at_serializes_to_epoch_seconds() -> None:
    created = datetime(2022, 1, 1, tzinfo=timezone.utc)
    dumped = _make_chunk(created_at=created, last_updated=None).model_dump()
    assert dumped[CREATED_AT_FIELD_NAME] == int(created.timestamp())


def test_created_at_round_trips_from_epoch_seconds() -> None:
    created = datetime(2022, 1, 1, tzinfo=timezone.utc)
    epoch = int(created.timestamp())
    parsed = DocumentChunkWithoutVectors.model_validate(
        {
            "document_id": "doc-1",
            "chunk_index": 0,
            "content": "hello",
            "source_type": "web",
            CREATED_AT_FIELD_NAME: epoch,
            "public": True,
            "access_control_list": [],
            "global_boost": 0,
            "semantic_identifier": "doc-1",
            "blurb": "hello",
            "doc_summary": "",
            "chunk_context": "",
        }
    )
    assert parsed.created_at == created
    assert parsed.created_at is not None
    assert parsed.created_at.tzinfo is not None


def test_naive_created_at_is_treated_as_utc() -> None:
    naive = datetime(2022, 1, 1)
    utc = datetime(2022, 1, 1, tzinfo=timezone.utc)
    dumped = _make_chunk(created_at=naive, last_updated=None).model_dump()
    assert dumped[CREATED_AT_FIELD_NAME] == int(utc.timestamp())


def test_unset_datetimes_are_omitted() -> None:
    dumped = _make_chunk(created_at=None, last_updated=None).model_dump()
    assert CREATED_AT_FIELD_NAME not in dumped
    assert LAST_UPDATED_FIELD_NAME not in dumped
