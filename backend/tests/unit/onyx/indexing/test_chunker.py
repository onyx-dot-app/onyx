import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
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
            Section(text=short_section_1, link="link1"),
            Section(text=short_section_2, link="link2"),
            Section(text=long_section, link="link3"),
            Section(text=short_section_3, link="link4"),
            Section(text=short_section_4, link="link5"),
        ],
    )

    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=False,
    )
    chunks = chunker.chunk([document])

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
            Section(text="This is a short section.", link="link1"),
        ],
    )

    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=False,
        callback=mock_heartbeat,
    )

    chunks = chunker.chunk([document])

    assert mock_heartbeat.call_count == 1
    assert len(chunks) > 0
