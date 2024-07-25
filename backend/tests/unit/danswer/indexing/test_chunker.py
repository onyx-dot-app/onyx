from danswer.configs.constants import DocumentSource
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.indexing.chunker import chunk_document


def test_chunk_document() -> None:
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

    chunks = chunk_document(document)
    assert len(chunks) == 5
    assert all(semantic_identifier in chunk.content for chunk in chunks)
    assert short_section_1 in chunks[0].content
    assert short_section_3 in chunks[-1].content
    assert short_section_4 in chunks[-1].content
    assert "tag1" in chunks[0].content
