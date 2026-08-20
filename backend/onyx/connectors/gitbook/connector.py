from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from urllib.parse import urljoin

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE, REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    TextSection,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

GITBOOK_API_BASE = "https://api.gitbook.com/v1/"


class GitbookApiClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        url = urljoin(GITBOOK_API_BASE, endpoint.lstrip("/"))
        response = requests.get(
            url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()

    def get_page_content(self, space_id: str, page_id: str) -> dict[str, Any]:
        return self.get(f"/spaces/{space_id}/content/page/{page_id}")


class BlockType(StrEnum):
    """GitBook document block types the renderer handles explicitly.

    Types not listed here fall back to rendering children and fragments."""

    HEADING_1 = "heading-1"
    HEADING_2 = "heading-2"
    HEADING_3 = "heading-3"
    HEADING_4 = "heading-4"
    HEADING_5 = "heading-5"
    HEADING_6 = "heading-6"
    PARAGRAPH = "paragraph"
    LIST_UNORDERED = "list-unordered"
    LIST_ORDERED = "list-ordered"
    LIST_TASKS = "list-tasks"
    CODE = "code"
    CODE_LINE = "code-line"
    BLOCKQUOTE = "blockquote"
    HINT = "hint"
    TABS_ITEM = "tabs-item"
    TABLE = "table"
    EMBED = "embed"
    MATH = "math"
    MATH_BLOCK = "math-block"
    DIVIDER = "divider"


class InlineType(StrEnum):
    LINK = "link"
    MATH = "math"
    INLINE_MATH = "inline-math"
    EMOJI = "emoji"


_HEADING_PREFIXES = {
    BlockType.HEADING_1: "#",
    BlockType.HEADING_2: "##",
    BlockType.HEADING_3: "###",
    BlockType.HEADING_4: "####",
    BlockType.HEADING_5: "#####",
    BlockType.HEADING_6: "######",
}
_LIST_TYPES = frozenset(
    {BlockType.LIST_UNORDERED, BlockType.LIST_ORDERED, BlockType.LIST_TASKS}
)


def _render_leaves(text_node: dict[str, Any]) -> str:
    return "".join(
        leaf.get("text", "")
        for leaf in text_node.get("leaves", [])
        if isinstance(leaf, dict)
    )


def _render_inline(node: dict[str, Any]) -> str:
    """Render an inline node (link, inline math, emoji, ...) to plain text."""
    inline_type = node.get("type", "")
    data = node.get("data") or {}
    text = _render_inline_nodes(node.get("nodes", []))

    if inline_type == InlineType.LINK:
        ref = data.get("ref") or {}
        url = ref.get("url", "") if isinstance(ref, dict) else ""
        if url and text:
            return f"[{text}]({url})"
        return text or url
    if inline_type in (InlineType.MATH, InlineType.INLINE_MATH):
        return str(data.get("formula", "")) or text
    if inline_type == InlineType.EMOJI:
        code = data.get("code", "")
        if isinstance(code, str) and code:
            try:
                return "".join(chr(int(part, 16)) for part in code.split("-"))
            except ValueError:
                pass
    return text


def _render_inline_nodes(nodes: list[Any]) -> str:
    """Render the mixed text/inline children of a paragraph-like node."""
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("object") == "inline":
            parts.append(_render_inline(node))
        elif "leaves" in node:
            parts.append(_render_leaves(node))
        else:
            parts.append(_render_inline_nodes(node.get("nodes", [])))
    return "".join(parts)


def _render_fragments(node: dict[str, Any], depth: int) -> str:
    """Fragments hold out-of-band content: image captions, expandable titles/bodies, etc.
    Table cell fragments are rendered by _render_table instead."""
    result = ""
    for fragment in node.get("fragments", []):
        if isinstance(fragment, dict):
            result += _render_blocks(fragment.get("nodes", []), depth)
    return result


def _render_children(node: dict[str, Any], depth: int) -> str:
    return _render_blocks(node.get("nodes", []), depth) + _render_fragments(node, depth)


def _quote_lines(text: str) -> str:
    stripped = text.strip("\n")
    if not stripped:
        return ""
    return (
        "".join(f"> {line}\n" if line else ">\n" for line in stripped.split("\n"))
        + "\n"
    )


def _render_list(node: dict[str, Any], depth: int) -> str:
    list_type = node.get("type", "")
    indent = "  " * depth
    result = ""

    for position, item in enumerate(node.get("nodes", []), start=1):
        if not isinstance(item, dict):
            continue

        if list_type == BlockType.LIST_ORDERED:
            marker = f"{position}. "
        elif list_type == BlockType.LIST_TASKS:
            checked = bool((item.get("data") or {}).get("checked", False))
            marker = "- [x] " if checked else "- [ ] "
        else:
            marker = "* "

        marker_text = ""
        marker_consumed = False
        nested: list[dict[str, Any]] = []
        for child in item.get("nodes", []):
            if not isinstance(child, dict):
                continue
            if not marker_consumed and child.get("type") == BlockType.PARAGRAPH:
                marker_text = _render_inline_nodes(child.get("nodes", [])).strip()
                marker_consumed = True
            else:
                nested.append(child)

        result += f"{indent}{marker}{marker_text}\n"
        for child in nested:
            if child.get("type") in _LIST_TYPES:
                result += _render_list(child, depth + 1)
            else:
                rendered = _render_block(child, depth + 1).strip("\n")
                for line in rendered.split("\n"):
                    if line:
                        result += f"{indent}  {line}\n"

    if depth == 0 and result:
        result += "\n"
    return result


def _escape_table_cell(text: str) -> str:
    lines = [line.strip() for line in text.replace("|", "\\|").split("\n")]
    return "<br>".join(line for line in lines if line)


def _table_select_label(value: str, col_def: dict[str, Any]) -> str:
    options = col_def.get("options")
    if isinstance(options, list):
        for option in options:
            if isinstance(option, dict) and option.get("id") == value:
                return str(option.get("label") or option.get("title") or value)
    elif isinstance(options, dict):
        option = options.get(value)
        if isinstance(option, dict):
            return str(option.get("label") or option.get("title") or value)
        if isinstance(option, str):
            return option
    return value


def _render_table_cell(
    value: Any,
    col_def: dict[str, Any],
    fragments_by_id: dict[str, dict[str, Any]],
) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        fragment = fragments_by_id.get(value)
        if fragment is not None:
            return _escape_table_cell(_render_blocks(fragment.get("nodes", []), 0))
        col_type = str(col_def.get("type", ""))
        if col_type == "select":
            return _escape_table_cell(_table_select_label(value, col_def))
        # an unresolved string in a fragment-backed table (or a text column)
        # is an opaque fragment id, not content
        if fragments_by_id or col_type == "text":
            return ""
        return _escape_table_cell(value)
    if isinstance(value, dict):
        # content-ref cells: only URL refs carry human-readable content
        ref = value if "kind" in value else value.get("ref") or {}
        url = ref.get("url", "") if isinstance(ref, dict) else ""
        return _escape_table_cell(str(url)) if url else ""
    if isinstance(value, list):
        rendered = [_render_table_cell(v, col_def, fragments_by_id) for v in value]
        return ", ".join(part for part in rendered if part)
    return ""


def _render_table(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    records = data.get("records") or {}
    definition = data.get("definition") or {}
    view = data.get("view") or {}

    columns = [
        col
        for col in (view.get("columns") or list(definition.keys()))
        if isinstance(col, str)
    ]
    if not columns or not isinstance(records, dict):
        # unrecognized table shape: surface all cell fragments as plain text
        return _render_fragments(node, 0)

    fragments_by_id: dict[str, dict[str, Any]] = {}
    for fragment in node.get("fragments", []):
        if isinstance(fragment, dict) and isinstance(fragment.get("fragment"), str):
            fragments_by_id[fragment["fragment"]] = fragment

    header = [
        _escape_table_cell(str((definition.get(col) or {}).get("title", "")))
        for col in columns
    ]
    result = "| " + " | ".join(header) + " |\n"
    result += "|" + "---|" * len(header) + "\n"

    sorted_records = sorted(
        (
            (record_id, record)
            for record_id, record in records.items()
            if isinstance(record, dict)
        ),
        key=lambda kv: str(kv[1].get("orderIndex", "")),
    )
    for _record_id, record in sorted_records:
        raw_values = record.get("values")
        values: dict[str, Any] = raw_values if isinstance(raw_values, dict) else {}
        cells = [
            _render_table_cell(
                values.get(col), definition.get(col) or {}, fragments_by_id
            )
            for col in columns
        ]
        result += "| " + " | ".join(cells) + " |\n"

    return result + "\n"


def _render_block(node: dict[str, Any], depth: int) -> str:
    block_type = node.get("type", "")
    data = node.get("data") or {}

    if "leaves" in node:
        text = _render_leaves(node).strip()
        return f"{text}\n\n" if text else ""

    if block_type in _HEADING_PREFIXES:
        text = _render_inline_nodes(node.get("nodes", [])).strip()
        return f"{_HEADING_PREFIXES[block_type]} {text}\n\n" if text else ""

    if block_type == BlockType.PARAGRAPH:
        text = _render_inline_nodes(node.get("nodes", [])).strip()
        return f"{text}\n\n" if text else ""

    if block_type in _LIST_TYPES:
        return _render_list(node, depth)

    if block_type == BlockType.CODE:
        syntax = str(data.get("syntax", ""))
        lines = [
            _render_inline_nodes(line.get("nodes", []))
            for line in node.get("nodes", [])
            if isinstance(line, dict) and line.get("type") == BlockType.CODE_LINE
        ]
        return f"```{syntax}\n" + "\n".join(lines) + "\n```\n\n"

    if block_type == BlockType.BLOCKQUOTE:
        return _quote_lines(_render_children(node, depth))

    if block_type == BlockType.HINT:
        style = str(data.get("style", ""))
        label = f"[!{style.upper()}]\n" if style else ""
        return _quote_lines(label + _render_children(node, depth).strip("\n"))

    if block_type == BlockType.TABS_ITEM:
        title = str(data.get("title", ""))
        return (f"**{title}**\n\n" if title else "") + _render_children(node, depth)

    if block_type == BlockType.TABLE:
        return _render_table(node)

    if block_type == BlockType.EMBED:
        url = str(data.get("url", ""))
        caption = _render_fragments(node, depth)
        return (f"{url}\n\n" if url else "") + caption

    if block_type in (BlockType.MATH, BlockType.MATH_BLOCK):
        formula = str(data.get("formula", ""))
        return f"{formula}\n\n" if formula else ""

    if block_type == BlockType.DIVIDER:
        return "---\n\n"

    # containers (tabs, expandable, columns, images, files, ...) and unknown
    # blocks: render children and fragments so no text silently disappears
    inner = _render_children(node, depth)
    if not inner and block_type:
        logger.debug("GitBook block type %s produced no text", block_type)
    return inner


def _render_blocks(nodes: list[Any], depth: int) -> str:
    return "".join(
        _render_block(node, depth) for node in nodes if isinstance(node, dict)
    )


def _extract_text_from_document(document: dict[str, Any]) -> str:
    """Extract text content from GitBook document structure by rendering the
    document nodes into markdown."""
    if not document or "document" not in document:
        return ""
    return _render_blocks(document["document"].get("nodes", []), 0)


def _parse_page_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _page_last_modified(page: dict[str, Any]) -> datetime | None:
    """updatedAt only exists once a page has been edited; fall back to createdAt."""
    return _parse_page_timestamp(page.get("updatedAt")) or _parse_page_timestamp(
        page.get("createdAt")
    )


def _convert_page_to_document(
    client: GitbookApiClient, space_id: str, page: dict[str, Any]
) -> Document:
    page_id = page["id"]
    page_content = client.get_page_content(space_id, page_id)

    text = _extract_text_from_document(page_content)

    return Document(
        id=f"gitbook-{space_id}-{page_id}",
        sections=[
            TextSection(
                link=page.get("urls", {}).get("app", ""),
                text=text,
            )
        ],
        source=DocumentSource.GITBOOK,
        semantic_identifier=page.get("title", ""),
        doc_updated_at=_page_last_modified(page),
        doc_created_at=_parse_page_timestamp(page.get("createdAt")),
        metadata={
            "path": page.get("path", ""),
            "type": page.get("type", ""),
            "kind": page.get("kind", ""),
        },
    )


class GitbookConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        space_id: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.space_id = space_id
        self.batch_size = batch_size
        self.access_token: str | None = None
        self.client: GitbookApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        access_token = credentials.get("gitbook_api_key")
        if not access_token:
            raise ConnectorMissingCredentialError("GitBook access token")
        self.access_token = access_token
        self.client = GitbookApiClient(access_token)

    def _fetch_all_pages(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        if not self.client:
            raise ConnectorMissingCredentialError("GitBook")

        try:
            content = self.client.get(f"/spaces/{self.space_id}/content/pages")
            pages: list[dict[str, Any]] = content.get("pages", [])
            current_batch: list[Document | HierarchyNode] = []

            logger.info("Found %s root pages.", len(pages))
            logger.info(
                "First 20 Page Ids: %s",
                [page.get("id", "Unknown") for page in pages[:20]],
            )

            while pages:
                page = pages.pop(0)

                # always traverse children, even if this page falls outside the window
                pages.extend(page.get("pages", []))

                last_modified = _page_last_modified(page)
                if last_modified is not None:
                    if start and last_modified < start:
                        continue
                    if end and last_modified > end:
                        continue

                current_batch.append(
                    _convert_page_to_document(self.client, self.space_id, page)
                )

                if len(current_batch) >= self.batch_size:
                    yield current_batch
                    current_batch = []

            if current_batch:
                yield current_batch

        except requests.RequestException as e:
            logger.error("Error fetching GitBook content: %s", str(e))
            raise

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_all_pages()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._fetch_all_pages(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = GitbookConnector(
        space_id=os.environ["GITBOOK_SPACE_ID"],
    )
    connector.load_credentials({"gitbook_api_key": os.environ["GITBOOK_API_KEY"]})
    document_batches = connector.load_from_state()
    print(next(document_batches))
