"""Rendering of Atlassian Document Format (ADF) content as plain text.

https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/

Jira Cloud returns every rich text field (description, comments, rich text
custom fields) as ADF. Block structure is preserved in the rendered output:
deployment tables, release checklists and step-by-step instructions only carry
meaning while each value stays attached to its row, column or list item.

The output is markdown-flavored plain text. Marks that are purely visual
(strong, emphasis, code, ...) are dropped; only links are kept, since a link
target is information that the surrounding text does not already contain.
"""

from datetime import datetime, timezone
from typing import Any

# Indentation added per nesting level of a list.
_LIST_INDENT = "  "

# Node types whose URL is the only content they carry.
_CARD_NODE_TYPES = frozenset({"inlineCard", "blockCard", "embedCard"})


def extract_text_from_adf(adf: dict[str, Any] | None) -> str:
    """Render an ADF document (or any single ADF node) as plain text."""
    if adf is None:
        return ""
    return "\n".join(_render_blocks(adf))


def _render_child_blocks(nodes: list[dict[str, Any]]) -> list[str]:
    blocks: list[str] = []
    for node in nodes:
        blocks.extend(_render_blocks(node))
    return blocks


def _render_blocks(node: dict[str, Any]) -> list[str]:
    """Render one ADF node as a list of text lines."""
    node_type = node.get("type")
    attrs = node.get("attrs") or {}
    content = node.get("content") or []

    if node_type == "paragraph":
        text = _render_inline(content)
        return [text] if text else []

    if node_type == "heading":
        text = _render_inline(content)
        level = attrs.get("level") or 1
        return [f"{'#' * int(level)} {text}"] if text else []

    if node_type == "codeBlock":
        code = _render_inline(content)
        return [f"```{attrs.get('language') or ''}", code, "```"] if code else []

    if node_type in ("bulletList", "orderedList"):
        return _render_list(node)

    if node_type in ("taskList", "decisionList"):
        return _render_task_list(content)

    if node_type == "table":
        return _render_table(content)

    if node_type == "blockquote":
        return [f"> {line}" for line in _render_child_blocks(content)]

    if node_type == "panel":
        # The panel type (info / warning / error / ...) is the reason the author
        # highlighted the block, so it is worth keeping.
        blocks = _render_child_blocks(content)
        panel_type = attrs.get("panelType")
        if not blocks or not panel_type:
            return blocks
        return [f"[{panel_type}] {blocks[0]}", *blocks[1:]]

    if node_type in ("expand", "nestedExpand"):
        title = attrs.get("title")
        blocks = _render_child_blocks(content)
        return [str(title), *blocks] if title else blocks

    if node_type == "media":
        # Only the caption/alt text is readable; the file itself is not indexed
        # by this connector.
        alt = attrs.get("alt")
        return [f"[media: {alt}]"] if alt else []

    if node_type == "rule":
        return []

    if content:
        # doc, listItem, mediaSingle, layoutSection, bodiedExtension and any node
        # type Atlassian adds later: keep the content, drop the wrapper.
        return _render_child_blocks(content)

    # Unknown leaf node (e.g. a new inline type used in block position): fall
    # back to whatever inline text it carries rather than dropping it.
    inline_text = _render_inline([node])
    return [inline_text] if inline_text else []


def _render_inline(nodes: list[dict[str, Any]]) -> str:
    """Concatenate inline nodes. ADF text nodes carry their own spacing."""
    parts: list[str] = []
    for node in nodes:
        node_type = node.get("type")
        attrs = node.get("attrs") or {}

        if node_type == "text":
            parts.append(_render_text_node(node))
        elif node_type == "hardBreak":
            parts.append("\n")
        elif node_type == "mention":
            parts.append(str(attrs.get("text") or attrs.get("displayName") or ""))
        elif node_type == "emoji":
            parts.append(str(attrs.get("text") or attrs.get("shortName") or ""))
        elif node_type == "date":
            parts.append(_render_timestamp(attrs.get("timestamp")))
        elif node_type == "status":
            parts.append(str(attrs.get("text") or ""))
        elif node_type in _CARD_NODE_TYPES:
            parts.append(_render_card_url(attrs))
        elif node.get("content"):
            parts.append(_render_inline(node["content"]))
        elif "text" in node:
            parts.append(str(node["text"]))

    return "".join(parts)


def _render_text_node(node: dict[str, Any]) -> str:
    text = str(node.get("text") or "")
    for mark in node.get("marks") or []:
        if mark.get("type") != "link":
            continue
        href = (mark.get("attrs") or {}).get("href")
        # Keep the target only when it is not already visible in the link text.
        if href and str(href) not in text:
            return f"{text} ({href})"
    return text


def _render_card_url(attrs: dict[str, Any]) -> str:
    url = attrs.get("url")
    if not url:
        # blockCard / embedCard variants nest the link inside JSON-LD data.
        data = attrs.get("data")
        if isinstance(data, dict):
            url = data.get("url") or data.get("@id")
    return str(url) if url else ""


def _render_timestamp(timestamp: Any) -> str:
    """ADF date nodes hold a unix timestamp in milliseconds."""
    try:
        millis = int(timestamp)
    except (TypeError, ValueError):
        return str(timestamp) if timestamp else ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _render_list(list_node: dict[str, Any]) -> list[str]:
    """Render a bullet/ordered list, indenting nested content one level in.

    List items are rendered unindented and indented here, so nested lists
    compose to the right depth without tracking depth through the recursion.
    """
    is_ordered = list_node.get("type") == "orderedList"
    first_number = (list_node.get("attrs") or {}).get("order") or 1

    blocks: list[str] = []
    for position, item in enumerate(list_node.get("content") or []):
        item_blocks = _render_child_blocks(item.get("content") or [])
        if not item_blocks:
            continue
        marker = f"{int(first_number) + position}." if is_ordered else "-"
        first_line, *continuation = item_blocks
        blocks.append(f"{marker} {first_line}")
        blocks.extend(f"{_LIST_INDENT}{line}" for line in continuation)
    return blocks


def _render_task_list(items: list[dict[str, Any]]) -> list[str]:
    blocks: list[str] = []
    for item in items:
        text = _render_inline(item.get("content") or [])
        if not text:
            continue
        if item.get("type") == "taskItem":
            state = (item.get("attrs") or {}).get("state")
            blocks.append(f"- [{'x' if state == 'DONE' else ' '}] {text}")
        else:
            blocks.append(f"- {text}")
    return blocks


def _render_table(rows: list[dict[str, Any]]) -> list[str]:
    """Render a table as markdown rows, keeping each value under its column."""
    rendered_rows: list[str] = []
    header_column_count = 0

    for row in rows:
        if row.get("type") != "tableRow":
            continue
        cells = row.get("content") or []
        cell_texts = [_render_table_cell(cell) for cell in cells]
        if not any(cell_texts):
            continue

        is_first_row = not rendered_rows
        rendered_rows.append("| " + " | ".join(cell_texts) + " |")
        if is_first_row and all(cell.get("type") == "tableHeader" for cell in cells):
            header_column_count = len(cell_texts)

    if header_column_count:
        rendered_rows.insert(1, "| " + " | ".join(["---"] * header_column_count) + " |")
    return rendered_rows


def _render_table_cell(cell: dict[str, Any]) -> str:
    """Flatten a cell to a single line; markdown rows cannot hold block content."""
    blocks = _render_child_blocks(cell.get("content") or [])
    joined = " ".join(block.replace("|", r"\|") for block in blocks)
    return " ".join(joined.split())
