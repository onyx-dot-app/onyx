from typing import Any
from unittest.mock import Mock

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


@pytest.mark.parametrize("enable_contextual_rag", [True, False])
def test_chunk_document(
    embedder: DefaultIndexingEmbedder, enable_contextual_rag: bool
) -> None:
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

    mock_llm_invoke_count = 0

    def mock_llm_invoke(self: Any, *args: Any, **kwargs: Any) -> Mock:
        nonlocal mock_llm_invoke_count
        mock_llm_invoke_count += 1
        m = Mock()
        m.content = f"Test{mock_llm_invoke_count}"
        return m

    mock_llm = Mock()
    mock_llm.invoke = mock_llm_invoke

    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=False,
        enable_contextual_rag=enable_contextual_rag,
        llm=mock_llm,
    )
    chunks = chunker.chunk([document])

    assert len(chunks) == 5
    assert short_section_1 in chunks[0].content
    assert short_section_3 in chunks[-1].content
    assert short_section_4 in chunks[-1].content
    assert "tag1" in chunks[0].metadata_suffix_keyword
    assert "tag2" in chunks[0].metadata_suffix_semantic

    doc_summary = "Test1" if enable_contextual_rag else ""
    chunk_context = ""
    count = 2
    for chunk in chunks:
        if enable_contextual_rag:
            chunk_context = f"Test{count}"
            count += 1
        assert chunk.doc_summary == doc_summary
        assert chunk.chunk_context == chunk_context


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
        enable_contextual_rag=False,
    )

    chunks = chunker.chunk([document])

    assert mock_heartbeat.call_count == 1
    assert len(chunks) > 0
