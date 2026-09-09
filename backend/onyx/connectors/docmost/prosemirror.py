"""Convert DocMost page content (ProseMirror / TipTap JSON) to plain text.

DocMost stores page bodies as a ProseMirror document tree (TipTap v3 as of
DocMost v0.25.0). This extractor walks the tree and produces readable plain
text suitable for indexing.

Indexed:        paragraphs, headings, list items, blockquotes, callouts,
                table cell text, code block contents (as plain text), and the
                visible text/links of inline marks.
Dropped:        mermaid diagram source, math/LaTeX source, and raw attributes —
                these add noise to retrieval rather than signal. (Tracked as a
                future refinement if we decide to index them.)

The walker is intentionally permissive: unknown node types fall through to a
generic "recurse into content" path so new TipTap nodes don't silently break
extraction.
"""

from typing import Any

# Node types whose *source* we deliberately skip (noise for search).
_SKIP_NODE_TYPES = {
    "mermaid",
    "mermaidDiagram",
    "math",
    "mathBlock",
    "mathInline",
    "katex",
}

# Block-level nodes that should be followed by a blank line.
_BLOCK_NODE_TYPES = {
    "paragraph",
    "heading",
    "blockquote",
    "codeBlock",
    "code_block",
    "listItem",
    "list_item",
    "callout",
    "details",
    "horizontalRule",
}


def prosemirror_to_text(content: Any) -> str:
    """Top-level entry point. Accepts the page's JSON content (dict or str).

    Returns a newline-joined plain-text rendering. Empty input yields "".
    """
    if content is None:
        return ""

    # DocMost may return content already-parsed (dict) or as a JSON string.
    if isinstance(content, str):
        import json

        try:
            content = json.loads(content)
        except (ValueError, TypeError):
            # Not JSON — treat the raw string as the text.
            return content.strip()

    if not isinstance(content, dict):
        return ""

    parts: list[str] = []
    _walk(content, parts)
    # Collapse runs of blank lines and trim.
    text = "\n".join(p for p in parts if p is not None)
    lines = [line.rstrip() for line in text.split("\n")]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if line == "":
            if not blank:
                cleaned.append("")
            blank = True
        else:
            cleaned.append(line)
            blank = False
    return "\n".join(cleaned).strip()


def _walk(node: dict[str, Any], parts: list[str]) -> None:
    node_type = node.get("type")

    if node_type in _SKIP_NODE_TYPES:
        return

    # Text leaf node.
    if node_type == "text":
        text = node.get("text", "")
        # If this text carries a link mark, append the URL so it stays searchable.
        for mark in node.get("marks", []) or []:
            if mark.get("type") == "link":
                href = (mark.get("attrs") or {}).get("href")
                if href and href not in text:
                    text = f"{text} ({href})"
        parts.append(text)
        return

    # Hard break.
    if node_type in ("hardBreak", "hard_break"):
        parts.append("\n")
        return

    # Headings: prefix with markdown-ish hashes for light structure.
    if node_type == "heading":
        level = int((node.get("attrs") or {}).get("level", 1))
        prefix = "#" * max(1, min(level, 6)) + " "
        inner: list[str] = []
        _walk_children(node, inner)
        parts.append("")
        parts.append(prefix + "".join(inner).strip())
        parts.append("")
        return

    # Code blocks: keep contents verbatim as plain text.
    if node_type in ("codeBlock", "code_block"):
        inner = []
        _walk_children(node, inner)
        parts.append("")
        parts.append("".join(inner))
        parts.append("")
        return

    # List items get a bullet prefix.
    if node_type in ("listItem", "list_item"):
        inner = []
        _walk_children(node, inner)
        text = "".join(inner).strip()
        if text:
            parts.append(f"- {text}")
        return

    # Generic block nodes: recurse, then add spacing.
    if node_type in _BLOCK_NODE_TYPES:
        inner = []
        _walk_children(node, inner)
        joined = "".join(inner).strip()
        if joined:
            parts.append(joined)
            parts.append("")
        return

    # Default: recurse into children.
    _walk_children(node, parts)


def _walk_children(node: dict[str, Any], parts: list[str]) -> None:
    for child in node.get("content", []) or []:
        if isinstance(child, dict):
            _walk(child, parts)
