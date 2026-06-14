"""Unit tests for Google Drive section extraction.

Regression coverage for the case where a Google Docs heading paragraph is
returned without a ``headingId`` (or without ``paragraphStyle`` at all). The
old code accessed ``paragraph["paragraphStyle"]["headingId"]`` directly, which
raised a ``KeyError`` and aborted indexing of the entire document. The fix
falls back to ``None`` so the document is still indexed, just with a section
link that has no ``#heading=`` anchor.
"""

from typing import Any

from onyx.connectors.google_drive.section_extraction import _extract_id_from_heading
from onyx.connectors.google_drive.section_extraction import get_tab_sections


def _heading_paragraph(text: str, paragraph_style: dict[str, Any]) -> dict[str, Any]:
    return {
        "paragraph": {
            "paragraphStyle": paragraph_style,
            "elements": [{"textRun": {"content": text}}],
        }
    }


def _body_paragraph(text: str) -> dict[str, Any]:
    return {
        "paragraph": {
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "elements": [{"textRun": {"content": text}}],
        }
    }


def _make_tab(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tabProperties": {"tabId": "t.0"},
        "documentTab": {"body": {"content": content}},
    }


def test_extract_id_from_heading_present() -> None:
    paragraph = {"paragraphStyle": {"headingId": "h.abc123"}}
    assert _extract_id_from_heading(paragraph) == "h.abc123"


def test_extract_id_from_heading_missing_heading_id() -> None:
    # Heading paragraph whose paragraphStyle lacks headingId (Google omits it
    # for some headings) — must not raise.
    paragraph = {"paragraphStyle": {"namedStyleType": "HEADING_1"}}
    assert _extract_id_from_heading(paragraph) is None


def test_extract_id_from_heading_missing_paragraph_style() -> None:
    # Defensive: paragraphStyle absent entirely — must not raise.
    assert _extract_id_from_heading({}) is None


def test_get_tab_sections_heading_without_heading_id_is_indexed() -> None:
    """A heading missing headingId should still produce an indexed section."""
    tab = _make_tab(
        [
            _heading_paragraph(
                "Intro\n", {"namedStyleType": "HEADING_1", "headingId": "h.first"}
            ),
            _body_paragraph("Body under intro.\n"),
            # Heading with no headingId — previously raised KeyError.
            _heading_paragraph("No Anchor\n", {"namedStyleType": "HEADING_2"}),
            _body_paragraph("Body under no-anchor heading.\n"),
        ]
    )

    sections = get_tab_sections(tab, doc_id="doc1")

    assert len(sections) == 2

    # First heading keeps its anchor.
    assert "#heading=h.first" in sections[0].link
    assert "Body under intro." in sections[0].text

    # Second heading has no anchor but its content is still indexed.
    assert "#heading=" not in sections[1].link
    assert "No Anchor" in sections[1].text
    assert "Body under no-anchor heading." in sections[1].text
