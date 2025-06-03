from typing import Any

from pydantic import BaseModel

from onyx.connectors.google_utils.resources import GoogleDocsService
from onyx.connectors.models import FormattedTextSection

HEADING_DELIMITER = "\n"


class CurrentHeading(BaseModel):
    id: str | None
    text: str
    level: int  # 1-6 for heading levels


def _build_gdoc_section_link(doc_id: str, tab_id: str, heading_id: str | None) -> str:
    """Builds a Google Doc link that jumps to a specific heading"""
    heading_str = f"#heading={heading_id}" if heading_id else ""
    return f"https://docs.google.com/document/d/{doc_id}/edit?tab={tab_id}{heading_str}"


def _extract_id_from_heading(paragraph: dict[str, Any]) -> str:
    """Extracts the id from a heading paragraph element"""
    return paragraph["paragraphStyle"]["headingId"]


def _get_heading_level(paragraph: dict[str, Any]) -> int:
    """Extract heading level from paragraph style"""
    if not ("paragraphStyle" in paragraph and "namedStyleType" in paragraph["paragraphStyle"]):
        return 0
    
    style = paragraph["paragraphStyle"]["namedStyleType"]
    if style == "TITLE":
        return 1
    elif style.startswith("HEADING_"):
        try:
            return int(style.split("_")[1])
        except (IndexError, ValueError):
            return 1
    return 0


def _extract_formatted_text_from_paragraph(paragraph: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extracts the text content and formatting from a paragraph element"""
    text_elements = []
    formatting_info = {
        "has_bold": False,
        "has_italic": False,
        "has_underline": False,
        "has_links": False,
        "links": []
    }
    
    for element in paragraph.get("elements", []):
        if "textRun" in element:
            text_content = element["textRun"].get("content", "")
            text_elements.append(text_content)
            
            text_style = element["textRun"].get("textStyle", {})
            if text_style.get("bold"):
                formatting_info["has_bold"] = True
            if text_style.get("italic"):
                formatting_info["has_italic"] = True
            if text_style.get("underline"):
                formatting_info["has_underline"] = True

        if "textStyle" in element and "link" in element["textStyle"]:
            link_url = element["textStyle"]["link"].get("url", "")
            formatting_info["has_links"] = True
            formatting_info["links"].append(link_url)
            text_elements.append(f"({link_url})")

        if "person" in element:
            name = element["person"].get("personProperties", {}).get("name", "")
            email = element["person"].get("personProperties", {}).get("email", "")
            person_str = "<Person|"
            if name:
                person_str += f"name: {name}, "
            if email:
                person_str += f"email: {email}"
            person_str += ">"
            text_elements.append(person_str)

        if "richLink" in element:
            props = element["richLink"].get("richLinkProperties", {})
            title = props.get("title", "")
            uri = props.get("uri", "")
            link_str = f"[{title}]({uri})"
            text_elements.append(link_str)
            formatting_info["has_links"] = True
            formatting_info["links"].append(uri)

    return "".join(text_elements), formatting_info


def _extract_formatted_text_from_table(table: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Extracts the text content and structure from a table element.
    """
    table_rows = []
    table_metadata = {
        "rows": len(table.get("tableRows", [])),
        "columns": 0,
        "has_header": False
    }

    for row_idx, row in enumerate(table.get("tableRows", [])):
        cells = row.get("tableCells", [])
        if row_idx == 0:
            table_metadata["columns"] = len(cells)
            table_metadata["has_header"] = True
        
        cell_contents = []
        for cell in cells:
            child_elements = cell.get("content", [])
            cell_text_parts = []
            for child_elem in child_elements:
                if "paragraph" not in child_elem:
                    continue
                text, _ = _extract_formatted_text_from_paragraph(child_elem["paragraph"])
                cell_text_parts.append(text)
            cell_contents.append("".join(cell_text_parts))
        table_rows.append(cell_contents)
    
    html_parts = ["<table>"]
    for row_idx, row in enumerate(table_rows):
        if row_idx == 0 and table_metadata["has_header"]:
            html_parts.append("<thead><tr>")
            for cell in row:
                html_parts.append(f"<th>{cell}</th>")
            html_parts.append("</tr></thead><tbody>")
        else:
            if row_idx == 1 and table_metadata["has_header"]:
                pass
            html_parts.append("<tr>")
            for cell in row:
                html_parts.append(f"<td>{cell}</td>")
            html_parts.append("</tr>")
    
    if table_metadata["has_header"]:
        html_parts.append("</tbody>")
    html_parts.append("</table>")
    
    table_html = "".join(html_parts)
    return table_html, table_metadata


def get_formatted_document_sections(
    docs_service: GoogleDocsService,
    doc_id: str,
) -> list[FormattedTextSection]:
    """Extracts sections from a Google Doc with formatting information preserved"""
    http_request = docs_service.documents().get(documentId=doc_id)
    http_request.uri += "&includeTabsContent=true"
    doc = http_request.execute()

    tabs = doc.get("tabs", {})
    sections: list[FormattedTextSection] = []
    for tab in tabs:
        sections.extend(get_formatted_tab_sections(tab, doc_id))
    return sections


def _is_heading(paragraph: dict[str, Any]) -> bool:
    """Checks if a paragraph (a block of text in a drive document) is a heading"""
    if not (
        "paragraphStyle" in paragraph
        and "namedStyleType" in paragraph["paragraphStyle"]
    ):
        return False

    style = paragraph["paragraphStyle"]["namedStyleType"]
    is_heading = style.startswith("HEADING_")
    is_title = style.startswith("TITLE")
    return is_heading or is_title


def _is_list_item(paragraph: dict[str, Any]) -> bool:
    """Checks if a paragraph is a list item"""
    return "bullet" in paragraph


def _get_list_metadata(paragraph: dict[str, Any]) -> dict[str, Any]:
    """Extract list metadata from paragraph"""
    bullet = paragraph.get("bullet", {})
    list_id = bullet.get("listId")
    nesting_level = bullet.get("nestingLevel", 0)
    
    glyph_type = bullet.get("glyph", {}).get("type", "")
    list_type = "unordered"  # default
    if glyph_type in ["DECIMAL", "ALPHA", "ROMAN"]:
        list_type = "ordered"
    
    return {
        "list_id": list_id,
        "nesting_level": nesting_level,
        "list_type": list_type,
        "glyph_type": glyph_type
    }


def _add_finished_formatted_section(
    sections: list[FormattedTextSection],
    doc_id: str,
    tab_id: str,
    current_heading: CurrentHeading,
    current_section: list[tuple[str, str, dict[str, Any]]],  # (text, element_type, metadata)
) -> None:
    """Adds finished sections to the list with proper formatting"""
    if not (current_section or current_heading.text):
        return

    if current_heading.text:
        header_text = current_heading.text.replace(HEADING_DELIMITER, "")
        heading_element_type = f"heading{current_heading.level}"
        sections.append(
            FormattedTextSection(
                text=header_text.strip(),
                element_type=heading_element_type,
                link=_build_gdoc_section_link(doc_id, tab_id, current_heading.id),
                formatting_metadata={"heading_level": current_heading.level}
            )
        )

    for text, element_type, metadata in current_section:
        if text.strip():
            sections.append(
                FormattedTextSection(
                    text=text.strip(),
                    element_type=element_type,
                    link=_build_gdoc_section_link(doc_id, tab_id, current_heading.id),
                    formatting_metadata=metadata
                )
            )


def get_formatted_tab_sections(tab: dict[str, Any], doc_id: str) -> list[FormattedTextSection]:
    tab_id = tab["tabProperties"]["tabId"]
    content = tab.get("documentTab", {}).get("body", {}).get("content", [])

    sections: list[FormattedTextSection] = []
    current_section: list[tuple[str, str, dict[str, Any]]] = []  # (text, element_type, metadata)
    current_heading = CurrentHeading(id=None, text="", level=0)

    for element in content:
        if "paragraph" in element:
            paragraph = element["paragraph"]

            if _is_heading(paragraph):
                _add_finished_formatted_section(
                    sections, doc_id, tab_id, current_heading, current_section
                )
                current_section = []

                heading_id = _extract_id_from_heading(paragraph)
                heading_text, _ = _extract_formatted_text_from_paragraph(paragraph)
                heading_level = _get_heading_level(paragraph)
                current_heading = CurrentHeading(
                    id=heading_id,
                    text=heading_text,
                    level=heading_level
                )
                continue

            elif _is_list_item(paragraph):
                text, formatting_info = _extract_formatted_text_from_paragraph(paragraph)
                if text.strip():
                    list_metadata = _get_list_metadata(paragraph)
                    list_metadata.update(formatting_info)
                    current_section.append((text, "list_item", list_metadata))

            else:
                text, formatting_info = _extract_formatted_text_from_paragraph(paragraph)
                if text.strip():
                    current_section.append((text, "paragraph", formatting_info))

        elif "table" in element:
            table_html, table_metadata = _extract_formatted_text_from_table(element["table"])
            if table_html.strip():
                current_section.append((table_html, "table", table_metadata))

    _add_finished_formatted_section(sections, doc_id, tab_id, current_heading, current_section)

    return sections
