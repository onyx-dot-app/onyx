"""Unit tests for the Markdown -> DOCX converter that replaced pypandoc."""

from io import BytesIO

from docx import Document

from onyx.server.features.build.session.md_to_docx import markdown_to_docx_bytes


def _render(md_text: str) -> Document:
    data = markdown_to_docx_bytes(md_text)
    # A .docx is a zip archive, which always starts with the "PK" magic bytes.
    assert data[:2] == b"PK"
    return Document(BytesIO(data))


def _paragraph_styles(doc: Document) -> list[str]:
    return [p.style.name for p in doc.paragraphs if p.text.strip()]


def test_empty_markdown_produces_valid_docx() -> None:
    doc = _render("")
    assert doc.tables == []


def test_headings_map_to_heading_styles() -> None:
    doc = _render("# H1\n\n## H2\n\n### H3\n")
    styles = _paragraph_styles(doc)
    assert "Heading 1" in styles
    assert "Heading 2" in styles
    assert "Heading 3" in styles
    texts = [p.text for p in doc.paragraphs]
    assert "H1" in texts and "H2" in texts and "H3" in texts


def test_inline_formatting_sets_run_properties() -> None:
    doc = _render("Plain **bold** and *italic* and ~~strike~~ and `code`.")
    runs = [r for p in doc.paragraphs for r in p.runs]
    assert any(r.text == "bold" and r.bold for r in runs)
    assert any(r.text == "italic" and r.italic for r in runs)
    assert any(r.text == "strike" and r.font.strike for r in runs)
    assert any(r.text == "code" and r.font.name == "Courier New" for r in runs)


def test_bulleted_and_numbered_and_nested_lists() -> None:
    md = "- a\n- b\n  - nested\n\n1. one\n2. two\n"
    doc = _render(md)
    styles = _paragraph_styles(doc)
    assert "List Bullet" in styles
    assert "List Bullet 2" in styles  # nested level
    assert "List Number" in styles


def test_block_quote_uses_quote_style() -> None:
    doc = _render("> quoted line\n")
    assert "Quote" in _paragraph_styles(doc)


def test_fenced_code_block_is_monospace() -> None:
    doc = _render("```python\ndef f():\n    return 1\n```\n")
    monospace_runs = [
        r.text for p in doc.paragraphs for r in p.runs if r.font.name == "Courier New"
    ]
    assert any("def f():" in t for t in monospace_runs)


def test_table_is_rendered_with_header_and_rows() -> None:
    md = "| Name | Value |\n|------|-------|\n| a | 1 |\n| b | 2 |\n"
    doc = _render(md)
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert (len(table.rows), len(table.columns)) == (3, 2)
    assert [c.text for c in table.rows[0].cells] == ["Name", "Value"]
    assert [c.text for c in table.rows[1].cells] == ["a", "1"]


def test_link_becomes_real_hyperlink() -> None:
    doc = _render("See [Onyx](https://onyx.app) for details.")
    xml = doc.element.xml
    assert "w:hyperlink" in xml
    # The visible link text is preserved.
    assert "Onyx" in xml


def test_link_without_url_falls_back_to_text() -> None:
    # An autolink-free bare reference still renders its text without crashing.
    doc = _render("[empty]()")
    assert any("empty" in p.text for p in doc.paragraphs)
