"""Convert Markdown to a DOCX document using mistune + python-docx.

This replaces the previous pypandoc/pandoc-binary based conversion used by the
build session "export as DOCX" feature. Bundling the ~150 MB pandoc binary
(via ``pypandoc-binary``) into the production image purely for a single
Markdown -> DOCX conversion was by far the cheapest large size win available,
so the conversion is reimplemented here on top of dependencies that are already
part of the backend image (``mistune`` and ``python-docx``).
"""

from dataclasses import dataclass
from dataclasses import replace
from io import BytesIO
from typing import Any

import mistune
from docx import Document
from docx.document import Document as DocxDocument
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import _Cell
from docx.text.paragraph import Paragraph

_MONOSPACE_FONT = "Courier New"
_CODE_FONT_SIZE = Pt(9)
_LINK_COLOR = "0563C1"
# python-docx ships built-in "List Bullet"/"List Number" styles plus numbered
# variants up to level 3 ("List Bullet 2", "List Bullet 3", ...). Deeper nesting
# reuses the level-3 style.
_MAX_LIST_LEVEL = 3

# Enable the table/strikethrough/url plugins so the AST matches what pandoc
# previously handled for GitHub-Flavored-Markdown style documents.
_markdown_parser = mistune.create_markdown(
    renderer=None,
    plugins=["table", "strikethrough", "url"],
)

Node = dict[str, Any]


@dataclass(frozen=True)
class _Fmt:
    """Inline formatting flags carried down through nested inline nodes."""

    bold: bool = False
    italic: bool = False
    strike: bool = False
    code: bool = False


def markdown_to_docx_bytes(md_text: str) -> bytes:
    """Render Markdown text to the bytes of a .docx file."""
    tokens = _markdown_parser(md_text)
    nodes: list[Node] = tokens if isinstance(tokens, list) else []

    document = Document()
    _render_blocks(document, nodes)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Block-level rendering
# --------------------------------------------------------------------------- #
def _render_blocks(document: DocxDocument, nodes: list[Node]) -> None:
    for node in nodes:
        node_type = node.get("type")
        if node_type in ("blank_line", "newline"):
            continue
        if node_type == "heading":
            level = min(int(node.get("attrs", {}).get("level", 1)), 6)
            paragraph = document.add_paragraph(style=f"Heading {level}")
            _add_runs(paragraph, node.get("children", []), _Fmt())
        elif node_type in ("paragraph", "block_text"):
            paragraph = document.add_paragraph()
            _add_runs(paragraph, node.get("children", []), _Fmt())
        elif node_type == "block_code":
            _render_code(document, node)
        elif node_type == "block_quote":
            _render_quote(document, node)
        elif node_type == "list":
            _render_list(document, node, level=0)
        elif node_type == "thematic_break":
            _render_thematic_break(document)
        elif node_type == "table":
            _render_table(document, node)
        elif "children" in node:
            # Unknown block wrapper: recurse so its content is not dropped.
            _render_blocks(document, node["children"])


def _render_code(document: DocxDocument, node: Node) -> None:
    raw = str(node.get("raw", "")).rstrip("\n")
    paragraph = document.add_paragraph()
    for index, line in enumerate(raw.split("\n")):
        if index:
            paragraph.add_run().add_break()
        run = paragraph.add_run(line)
        run.font.name = _MONOSPACE_FONT
        run.font.size = _CODE_FONT_SIZE


def _render_quote(document: DocxDocument, node: Node) -> None:
    for child in node.get("children", []):
        if child.get("type") == "paragraph":
            paragraph = document.add_paragraph(style="Quote")
            _add_runs(paragraph, child.get("children", []), _Fmt())
        else:
            _render_blocks(document, [child])


def _render_list(document: DocxDocument, node: Node, level: int) -> None:
    ordered = bool(node.get("attrs", {}).get("ordered", False))
    base_style = "List Number" if ordered else "List Bullet"
    style_level = min(level + 1, _MAX_LIST_LEVEL)
    style = base_style if style_level == 1 else f"{base_style} {style_level}"

    for item in node.get("children", []):
        if item.get("type") != "list_item":
            continue
        for child in item.get("children", []):
            child_type = child.get("type")
            if child_type in ("block_text", "paragraph"):
                paragraph = document.add_paragraph(style=style)
                _add_runs(paragraph, child.get("children", []), _Fmt())
            elif child_type == "list":
                _render_list(document, child, level + 1)
            else:
                _render_blocks(document, [child])


def _render_thematic_break(document: DocxDocument) -> None:
    paragraph = document.add_paragraph()
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")
    borders.append(bottom)
    p_pr.append(borders)


def _render_table(document: DocxDocument, node: Node) -> None:
    header_cells: list[Node] = []
    body_rows: list[list[Node]] = []
    for section in node.get("children", []):
        section_type = section.get("type")
        if section_type == "table_head":
            header_cells = section.get("children", [])
        elif section_type == "table_body":
            for row in section.get("children", []):
                body_rows.append(row.get("children", []))

    num_cols = len(header_cells) or (len(body_rows[0]) if body_rows else 0)
    if num_cols == 0:
        return

    table = document.add_table(rows=0, cols=num_cols)
    try:
        table.style = "Table Grid"
    except KeyError:
        pass

    if header_cells:
        cells = table.add_row().cells
        for index, cell_node in enumerate(header_cells[:num_cols]):
            _fill_cell(cells[index], cell_node, bold=True)
    for row in body_rows:
        cells = table.add_row().cells
        for index, cell_node in enumerate(row[:num_cols]):
            _fill_cell(cells[index], cell_node, bold=False)


def _fill_cell(cell: _Cell, cell_node: Node, bold: bool) -> None:
    paragraph = cell.paragraphs[0]
    _add_runs(paragraph, cell_node.get("children", []), _Fmt(bold=bold))


# --------------------------------------------------------------------------- #
# Inline rendering
# --------------------------------------------------------------------------- #
def _add_runs(paragraph: Paragraph, nodes: list[Node], fmt: _Fmt) -> None:
    for node in nodes:
        node_type = node.get("type")
        if node_type == "text":
            _styled_run(paragraph, str(node.get("raw", "")), fmt)
        elif node_type == "strong":
            _add_runs(paragraph, node.get("children", []), replace(fmt, bold=True))
        elif node_type == "emphasis":
            _add_runs(paragraph, node.get("children", []), replace(fmt, italic=True))
        elif node_type == "strikethrough":
            _add_runs(paragraph, node.get("children", []), replace(fmt, strike=True))
        elif node_type == "codespan":
            _styled_run(paragraph, str(node.get("raw", "")), replace(fmt, code=True))
        elif node_type == "link":
            _add_hyperlink(paragraph, node, fmt)
        elif node_type == "image":
            alt = _collect_text(node.get("children", []))
            _styled_run(paragraph, f"[image: {alt}]" if alt else "[image]", fmt)
        elif node_type == "softbreak":
            _styled_run(paragraph, " ", fmt)
        elif node_type == "linebreak":
            paragraph.add_run().add_break()
        elif "children" in node:
            _add_runs(paragraph, node["children"], fmt)
        elif "raw" in node:
            _styled_run(paragraph, str(node["raw"]), fmt)


def _styled_run(paragraph: Paragraph, text: str, fmt: _Fmt) -> None:
    run = paragraph.add_run(text)
    run.bold = fmt.bold
    run.italic = fmt.italic
    if fmt.strike:
        run.font.strike = True
    if fmt.code:
        run.font.name = _MONOSPACE_FONT


def _add_hyperlink(paragraph: Paragraph, node: Node, fmt: _Fmt) -> None:
    url = str(node.get("attrs", {}).get("url", ""))
    text = _collect_text(node.get("children", [])) or url
    if not url:
        _styled_run(paragraph, text, fmt)
        return

    r_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    run_props = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), _LINK_COLOR)
    run_props.append(color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    run_props.append(underline)
    run.append(run_props)
    text_el = OxmlElement("w:t")
    text_el.text = text
    run.append(text_el)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _collect_text(nodes: list[Node]) -> str:
    parts: list[str] = []
    for node in nodes:
        if node.get("type") == "text":
            parts.append(str(node.get("raw", "")))
        elif node.get("children"):
            parts.append(_collect_text(node["children"]))
        elif "raw" in node:
            parts.append(str(node["raw"]))
    return "".join(parts)
