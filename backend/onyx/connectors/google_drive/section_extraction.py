from typing import Any

from pydantic import BaseModel

from onyx.connectors.google_utils.resources import GoogleDocsService
from onyx.connectors.models import Section


class CurrentHeading(BaseModel):
    id: str
    text: str


def _build_gdoc_section_link(doc_id: str, heading_id: str) -> str:
    """Builds a Google Doc link that jumps to a specific heading"""
    # NOTE: doesn't support docs with multiple tabs atm, if we need that ask
    # @Chris
    return (
        f"https://docs.google.com/document/d/{doc_id}/edit?tab=t.0#heading={heading_id}"
    )


def _extract_id_from_heading(paragraph: dict[str, Any]) -> str:
    """Extracts the id from a heading paragraph element"""
    return paragraph["paragraphStyle"]["headingId"]


def _extract_text_from_paragraph(paragraph: dict[str, Any]) -> str:
    """Extracts the text content from a paragraph element"""
    text_elements = []
    for element in paragraph.get("elements", []):
        if "textRun" in element:
            text_elements.append(element["textRun"].get("content", ""))
    return "".join(text_elements)


def get_document_sections(
    docs_service: GoogleDocsService,
    doc_id: str,
) -> list[Section]:
    """Extracts sections from a Google Doc, including their headings and content"""
    # Fetch the document structure
    doc = docs_service.documents().get(documentId=doc_id).execute()

    # Get the content
    content = doc.get("body", {}).get("content", [])

    sections: list[Section] = []
    current_section: list[str] = []
    current_heading: CurrentHeading | None = None

    for element in content:
        if "paragraph" not in element:
            continue

        paragraph = element["paragraph"]

        # Check if this is a heading
        if (
            "paragraphStyle" in paragraph
            and "namedStyleType" in paragraph["paragraphStyle"]
        ):
            style = paragraph["paragraphStyle"]["namedStyleType"]
            is_heading = style.startswith("HEADING_")
            is_title = style.startswith("TITLE")

            if is_heading or is_title:
                # If we were building a previous section, add it to sections list
                if current_heading is not None and current_section:
                    heading_text = current_heading.text
                    section_text = f"{heading_text}\n" + "\n".join(current_section)
                    sections.append(
                        Section(
                            text=section_text.strip(),
                            link=_build_gdoc_section_link(doc_id, current_heading.id),
                        )
                    )
                    current_section = []

                # Start new heading
                heading_id = _extract_id_from_heading(paragraph)
                heading_text = _extract_text_from_paragraph(paragraph)
                current_heading = CurrentHeading(
                    id=heading_id,
                    text=heading_text,
                )
                continue

        # Add content to current section
        if current_heading is not None:
            text = _extract_text_from_paragraph(paragraph)
            if text.strip():
                current_section.append(text)

    # Don't forget to add the last section
    if current_heading is not None and current_section:
        section_text = f"{current_heading.text}\n" + "\n".join(current_section)
        sections.append(
            Section(
                text=section_text.strip(),
                link=_build_gdoc_section_link(doc_id, current_heading.id),
            )
        )

    return sections
