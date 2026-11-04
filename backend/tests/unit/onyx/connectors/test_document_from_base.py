from onyx.connectors.models import Document, DocumentBase, TextSection


def test_from_base_keeps_source_type_and_size() -> None:
    base = DocumentBase(
        id="doc-1",
        sections=[TextSection(text="hello")],
        semantic_identifier="report.pdf",
        metadata={},
        source_mime_type="application/pdf",
        source_size_bytes=2048,
    )

    document = Document.from_base(base)

    assert document.source_mime_type == "application/pdf"
    assert document.source_size_bytes == 2048
