from datetime import datetime

from ee.onyx.external_permissions.salesforce.postprocessing import (
    censor_salesforce_chunks,
)
from onyx.configs.app_configs import BLURB_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.salesforce.utils import BASE_DATA_PATH
from onyx.context.search.models import InferenceChunk

SQLITE_DIR = BASE_DATA_PATH


def create_test_chunk(
    doc_id: str,
    chunk_id: int,
    content: str,
    source_links: dict[int, str] | None,
) -> InferenceChunk:
    return InferenceChunk(
        document_id=doc_id,
        chunk_id=chunk_id,
        blurb=content[:BLURB_SIZE],
        content=content,
        source_links=source_links,
        section_continuation=False,
        source_type=DocumentSource.SALESFORCE,
        semantic_identifier="test_chunk",
        title="Test Chunk",
        boost=1,
        recency_bias=1.0,
        score=None,
        hidden=False,
        metadata={},
        match_highlights=[],
        updated_at=datetime.now(),
        image_file_id=None,
        doc_summary="",
        chunk_context="",
    )


def test_validate_salesforce_access_single_object() -> None:
    """Test filtering when chunk has a single Salesforce object reference"""

    section = "This is a test document about a Salesforce object."
    test_content = section
    test_chunk = create_test_chunk(
        doc_id="doc1",
        chunk_id=1,
        content=test_content,
        source_links={0: "https://salesforce.com/object1"},
    )

    # Test when user has access
    filtered_chunks = censor_salesforce_chunks(
        chunks=[test_chunk],
        user_email="test@example.com",
        access_map={"object1": True},
    )
    assert len(filtered_chunks) == 1
    assert filtered_chunks[0].content == test_content

    # Test when user doesn't have access
    filtered_chunks = censor_salesforce_chunks(
        chunks=[test_chunk],
        user_email="test@example.com",
        access_map={"object1": False},
    )
    assert len(filtered_chunks) == 0


def test_validate_salesforce_access_multiple_objects() -> None:
    """Test filtering when chunk has multiple Salesforce object references"""
    section1 = "First part about object1. "
    section2 = "Second part about object2. "
    section3 = "Third part about object3."

    test_content = section1 + section2 + section3
    section1_end = len(section1)
    section2_end = section1_end + len(section2)

    test_chunk = create_test_chunk(
        doc_id="doc1",
        chunk_id=1,
        content=test_content,
        source_links={
            0: "https://salesforce.com/object1",
            section1_end: "https://salesforce.com/object2",
            section2_end: "https://salesforce.com/object3",
        },
    )

    # Test when user has access to all objects
    filtered_chunks = censor_salesforce_chunks(
        chunks=[test_chunk],
        user_email="test@example.com",
        access_map={
            "object1": True,
            "object2": True,
            "object3": True,
        },
    )
    assert len(filtered_chunks) == 1
    assert filtered_chunks[0].content == test_content

    # Test when user has access to some objects
    filtered_chunks = censor_salesforce_chunks(
        chunks=[test_chunk],
        user_email="test@example.com",
        access_map={
            "object1": True,
            "object2": False,
            "object3": True,
        },
    )
    assert len(filtered_chunks) == 1
    assert section1 in filtered_chunks[0].content
    assert section2 not in filtered_chunks[0].content
    assert section3 in filtered_chunks[0].content

    # Test when user has no access
    filtered_chunks = censor_salesforce_chunks(
        chunks=[test_chunk],
        user_email="test@example.com",
        access_map={
            "object1": False,
            "object2": False,
            "object3": False,
        },
    )
    assert len(filtered_chunks) == 0


def test_validate_salesforce_access_multiple_chunks() -> None:
    """Test filtering when there are multiple chunks with different access patterns"""
    section1 = "Content about object1"
    section2 = "Content about object2"

    chunk1 = create_test_chunk(
        doc_id="doc1",
        chunk_id=1,
        content=section1,
        source_links={0: "https://salesforce.com/object1"},
    )
    chunk2 = create_test_chunk(
        doc_id="doc1",
        chunk_id=2,
        content=section2,
        source_links={0: "https://salesforce.com/object2"},
    )

    # Test mixed access
    filtered_chunks = censor_salesforce_chunks(
        chunks=[chunk1, chunk2],
        user_email="test@example.com",
        access_map={
            "object1": True,
            "object2": False,
        },
    )
    assert len(filtered_chunks) == 1
    assert filtered_chunks[0].chunk_id == 1
    assert section1 in filtered_chunks[0].content


def test_validate_salesforce_access_no_source_links() -> None:
    """Test handling of chunks with no source links"""
    section = "Content with no source links"
    test_chunk = create_test_chunk(
        doc_id="doc1",
        chunk_id=1,
        content=section,
        source_links=None,
    )

    filtered_chunks = censor_salesforce_chunks(
        chunks=[test_chunk],
        user_email="test@example.com",
        access_map={},
    )
    assert len(filtered_chunks) == 0


def test_validate_salesforce_access_blurb_update() -> None:
    """Test that blurbs are properly updated based on permitted content"""
    section = "First part about object1. "
    long_content = section * 20  # Make it longer than BLURB_SIZE
    test_chunk = create_test_chunk(
        doc_id="doc1",
        chunk_id=1,
        content=long_content,
        source_links={0: "https://salesforce.com/object1"},
    )

    filtered_chunks = censor_salesforce_chunks(
        chunks=[test_chunk],
        user_email="test@example.com",
        access_map={"object1": True},
    )
    assert len(filtered_chunks) == 1
    assert len(filtered_chunks[0].blurb) <= BLURB_SIZE
    assert filtered_chunks[0].blurb.startswith(section)
