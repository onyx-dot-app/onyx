import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import process_image_sections
from tests.unit.onyx.indexing.conftest import MockHeartbeat


@pytest.fixture
def embedder() -> DefaultIndexingEmbedder:
    return DefaultIndexingEmbedder(
        model_name="intfloat/e5-base-v2",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
    )


def test_chunk_document(embedder: DefaultIndexingEmbedder) -> None:
    short_section_1 = "This is a short section."
    long_section = (
        "This is a long section that should be split into multiple chunks. " * 100
    )
    short_section_2 = "This is another short section."
    short_section_3 = "This is another short section again."
    short_section_4 = "Final short section."
    semantic_identifier = "Test Document"

    document = Document(
        id="test_doc",
        source=DocumentSource.WEB,
        semantic_identifier=semantic_identifier,
        metadata={"tags": ["tag1", "tag2"]},
        doc_updated_at=None,
        sections=[
            TextSection(text=short_section_1, link="link1"),
            TextSection(text=short_section_2, link="link2"),
            TextSection(text=long_section, link="link3"),
            TextSection(text=short_section_3, link="link4"),
            TextSection(text=short_section_4, link="link5"),
        ],
    )
    indexing_documents = process_image_sections([document])

    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=False,
    )
    chunks = chunker.chunk(indexing_documents)

    assert len(chunks) == 5
    assert short_section_1 in chunks[0].content
    assert short_section_3 in chunks[-1].content
    assert short_section_4 in chunks[-1].content
    assert "tag1" in chunks[0].metadata_suffix_keyword
    assert "tag2" in chunks[0].metadata_suffix_semantic


def test_chunker_heartbeat(
    embedder: DefaultIndexingEmbedder, mock_heartbeat: MockHeartbeat
) -> None:
    document = Document(
        id="test_doc",
        source=DocumentSource.WEB,
        semantic_identifier="Test Document",
        metadata={"tags": ["tag1", "tag2"]},
        doc_updated_at=None,
        sections=[
            TextSection(text="This is a short section.", link="link1"),
        ],
    )
    indexing_documents = process_image_sections([document])

    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=False,
        callback=mock_heartbeat,
    )

    chunks = chunker.chunk(indexing_documents)

    assert mock_heartbeat.call_count == 1
    assert len(chunks) > 0
