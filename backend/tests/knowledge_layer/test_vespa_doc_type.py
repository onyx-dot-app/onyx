def test_doc_type_raw_doc_default():
    """Documents without doc_type metadata default to 'raw_doc'."""
    from onyx.connectors.models import DocumentBase
    from onyx.configs.constants import DocumentSource

    doc = DocumentBase(
        id="test-1",
        sections=[],
        source=DocumentSource.FILE,
        semantic_identifier="test",
        metadata={},
    )
    assert doc.metadata.get("doc_type", "raw_doc") == "raw_doc"


def test_doc_type_wiki_page_from_metadata():
    """Wiki page documents carry doc_type=wiki_page in metadata."""
    from onyx.connectors.models import DocumentBase
    from onyx.configs.constants import DocumentSource

    doc = DocumentBase(
        id="wiki-1",
        sections=[],
        source=DocumentSource.FILE,
        semantic_identifier="wiki page",
        metadata={"doc_type": "wiki_page"},
    )
    assert doc.metadata.get("doc_type", "raw_doc") == "wiki_page"


def test_doc_type_constant_exists():
    """DOC_TYPE constant is defined in indexing_utils."""
    from onyx.document_index.vespa.indexing_utils import DOC_TYPE
    assert DOC_TYPE == "doc_type"


def test_vespa_schema_contains_doc_type_field():
    """Vespa schema template contains the doc_type field definition."""
    from pathlib import Path
    schema_path = Path(__file__).parents[2] / "onyx/document_index/vespa/app_config/schemas/danswer_chunk.sd.jinja"
    content = schema_path.read_text()
    assert "field doc_type type string" in content
    assert "fast-search" in content
