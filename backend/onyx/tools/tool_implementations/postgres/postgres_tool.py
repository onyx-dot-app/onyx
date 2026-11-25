"""Postgres query tool: structured, ACL-safe queries over a small allowlist
of metadata tables, as an alternative to semantic search for questions about
metadata, counting, structure, or the user's own chat history.

The LLM supplies fully-typed filter arguments (no NL-to-filter translation, so
`run()` makes no LLM call). All queries go through the restricted query layer
in `onyx.db.postgres_tool`, which enforces per-table access control, row caps,
and a statement timeout.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.access.hierarchy_access import get_user_external_group_ids
from onyx.agents.tools import ToolInvocation
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.chat import translate_db_search_doc_to_saved_search_doc
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HierarchyNodeType
from onyx.db.models import (
    ChatMessage,
    ChatSession,
    Document,
    HierarchyNode,
    User,
)
from onyx.db.postgres_tool import (
    POSTGRES_TOOL_DEFAULT_LIMIT,
    POSTGRES_TOOL_MAX_LIMIT,
    DocumentGroupBy,
    PostgresToolQueryTimeoutError,
    count_chat_messages_by_month_for_tool,
    count_chat_messages_for_tool,
    count_chat_sessions_by_month_for_tool,
    count_chat_sessions_for_tool,
    count_documents_for_tool,
    count_documents_grouped_for_tool,
    count_hierarchy_nodes_for_tool,
    count_search_docs_for_tool,
    query_chat_messages_for_tool,
    query_chat_sessions_for_tool,
    query_documents_for_tool,
    query_hierarchy_nodes_for_tool,
    query_search_docs_for_tool,
    tool_transaction,
    try_count_documents_for_tool,
)
from onyx.db.postgres_tool_models import (
    DocumentCursor,
    DocumentOrder,
    DocumentScope,
    GroupCount,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.constants import POSTGRES_TOOL_NAME
from onyx.tools.interface import CITATIONS_PER_TOOL_CALL, Tool
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultKind,
    CodeModeResultSpec,
    ToolCallException,
    ToolContext,
)
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.postgres.content import (
    CONTENT_FILTER_AVAILABLE,
    MAX_COUNT,
    ContentCursor,
    ContentFilter,
    ContentPath,
    date_field_for_order,
)
from onyx.tools.tool_implementations.postgres.models import (
    CHAT_HISTORY_TABLES,
    PostgresQueryArgs,
    PostgresToolTable,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MESSAGE_SNIPPET_CHARS = 300

# Programs get the same text the model sees; listed documents take citation
# numbers from the block that code mode reserves for the call.
_CODE_MODE_RESULT = CodeModeResultSpec(
    kind=CodeModeResultKind.TEXT,
    annotation="str",
    cites=True,
    returns=(
        "The result as text. Listed documents carry citation numbers like [3]. "
        "When more documents match, the last line is `next_cursor: <token>`; "
        "pass the token as cursor= with the same filters for the next page."
    ),
)

# The knowledge scope applies to documents and folders. Chat history is the
# user's own and is never scoped.
_SCOPED_TABLES = frozenset(
    {PostgresToolTable.DOCUMENT, PostgresToolTable.HIERARCHY_NODE}
)
_SCOPE_NOTE = "Results are limited to this agent's knowledge and this chat's filters."
_NO_SOURCES_MESSAGE = (
    "This chat's search filters exclude every source, so no documents or folders match."
)
_USER_FILES_ONLY_MESSAGE = (
    "This agent's knowledge is limited to uploaded files, which this tool "
    "cannot see. Use the search tool to look through them."
)


# The tool schema IS the column allowlist: only these filters exist, and each
# only applies to its table.
_FILTER_FIELDS_BY_TABLE: dict[PostgresToolTable, frozenset[str]] = {
    PostgresToolTable.DOCUMENT: frozenset(
        {
            "source_type",
            "title_contains",
            "updated_after",
            "updated_before",
            "owned_by",
            "parent_hierarchy_node_id",
            "content_contains",
        }
    ),
    PostgresToolTable.HIERARCHY_NODE: frozenset(
        {"source_type", "name_contains", "parent_id", "node_type"}
    ),
    PostgresToolTable.CHAT_SESSION: frozenset(
        {"description_contains", "created_after", "created_before"}
    ),
    PostgresToolTable.CHAT_MESSAGE: frozenset(
        {
            "chat_session_id",
            "content_contains",
            "message_type",
            "sent_after",
            "sent_before",
        }
    ),
    PostgresToolTable.SEARCH_DOC: frozenset({"chat_message_id", "cited_only"}),
}

_GROUP_BY_BY_TABLE: dict[PostgresToolTable, frozenset[str]] = {
    PostgresToolTable.DOCUMENT: frozenset({"source", "owner"}),
    PostgresToolTable.CHAT_SESSION: frozenset({"month"}),
    PostgresToolTable.CHAT_MESSAGE: frozenset({"month"}),
}

_DATE_FIELDS = frozenset(
    {
        "updated_after",
        "updated_before",
        "created_after",
        "created_before",
        "sent_after",
        "sent_before",
    }
)

# Filters that take one value or a list of values, any of which may match.
_ANY_OF_FIELDS = frozenset(
    {
        "source_type",
        "title_contains",
        "owned_by",
        "parent_hierarchy_node_id",
        "name_contains",
        "parent_id",
        "node_type",
        "description_contains",
        "chat_session_id",
        "content_contains",
    }
)
_MAX_ANY_OF_VALUES = 20
# Longer document content phrases are rejected.
_MAX_CONTENT_PHRASE_CHARS = 200

_GENERAL_FIELDS = frozenset(
    {"table", "count", "group_by", "limit", "cursor", "order_by"}
)


def _prop(
    json_type: str, description: str, enum: list[str] | None = None
) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": json_type, "description": description}
    if enum is not None:
        prop["enum"] = enum
    return prop


def _any_of_prop(
    item_type: str, description: str, enum: list[str] | None = None
) -> dict[str, Any]:
    # One value or a list: code mode type-checks calls against this schema.
    value = _prop(item_type, "One value.", enum)
    return {
        "anyOf": [value, {"type": "array", "items": value}],
        "description": f"{description} One value, or a list that matches any of its values (up to {_MAX_ANY_OF_VALUES}).",
    }


# fmt: off
_PARAMETER_SCHEMA: dict[str, dict[str, Any]] = {
    "table": _prop("string", "Which table to query.", [t.value for t in PostgresToolTable]),
    "count": _prop("boolean", "Return only the number of matching rows (default false)."),
    "group_by": _prop("string", "Only with count=true: break the count down. document: 'source' or 'owner'; chat_session/chat_message: 'month'.", ["source", "owner", "month"]),
    "limit": _prop("integer", f"Max rows to return (default {POSTGRES_TOOL_DEFAULT_LIMIT}, max {POSTGRES_TOOL_MAX_LIMIT}). For document listings, the page size."),
    "cursor": _prop("string", "document listings only: the next_cursor value from the previous page, to get the next page. Use the same filters and order_by as that call."),
    "order_by": _prop("string", "document listings only: row order (default 'updated_desc', newest first). With limit, gives the first N in that order in one call, e.g. the 10 oldest docs. Docs with no value sort last.", [o.value for o in DocumentOrder]),
    "source_type": _any_of_prop("string", "document/hierarchy_node: connector source id, e.g. 'confluence', 'google_drive', 'slack', 'web'."),
    "title_contains": _any_of_prop("string", "document: case-insensitive title substring, matched literally (% and _ are not wildcards; do not escape them)."),
    "updated_after": _prop("string", "document: ISO date lower bound on when the doc changed at its source. Docs with unknown source timestamps never match date filters."),
    "updated_before": _prop("string", "document: ISO date upper bound, exclusive (use the next day's date to include a whole day)."),
    "owned_by": _any_of_prop("string", "document: owner exactly as shown in a row's owners= field (usually a display name, sometimes an email; exact match). group_by=owner lists the stored values."),
    "parent_hierarchy_node_id": _any_of_prop("integer", "document: only docs directly inside this folder/space node."),
    "name_contains": _any_of_prop("string", "hierarchy_node: case-insensitive name substring."),
    "parent_id": _any_of_prop("integer", "hierarchy_node: list child nodes of this node."),
    "node_type": _any_of_prop("string", "hierarchy_node: e.g. 'folder', 'shared_drive', 'source'."),
    "description_contains": _any_of_prop("string", "chat_session: case-insensitive substring of the conversation title."),
    "created_after": _prop("string", "chat_session: ISO date lower bound."),
    "created_before": _prop("string", "chat_session: ISO date upper bound, exclusive."),
    "chat_session_id": _any_of_prop("string", "chat_message: only messages in this session (UUID)."),
    "content_contains": _any_of_prop("string", "chat_message: case-insensitive substring of the message text. document: documents whose text contains this word or phrase (with the default analyzer, matches are whole-word and case-insensitive, and word forms such as plurals match; the text includes the start of the title, the indexed metadata and any AI-generated summaries; Salesforce is searched only under public connectors; each indexed section of a document is matched on its own, so a phrase that crosses two sections can be missed). Slow on documents: use it only when the user wants an exhaustive list or count by content, add date, source or folder filters when you can, and use search to answer questions about what documents say. Document listings with it order by date only."),
    "message_type": _prop("string", "chat_message: filter by author.", ["user", "assistant"]),
    "sent_after": _prop("string", "chat_message: ISO date lower bound."),
    "sent_before": _prop("string", "chat_message: ISO date upper bound, exclusive."),
    "chat_message_id": _prop("integer", "search_doc (required): the past chat message whose sources to fetch."),
    "cited_only": _prop("boolean", "search_doc: true (default) = only docs the answer actually cited, in citation order; false = everything retrieved."),
}
# fmt: on

_NOUN_BY_TABLE: dict[PostgresToolTable, str] = {
    PostgresToolTable.DOCUMENT: "documents",
    PostgresToolTable.HIERARCHY_NODE: "hierarchy nodes",
    PostgresToolTable.CHAT_SESSION: "chat sessions",
    PostgresToolTable.CHAT_MESSAGE: "chat messages",
    PostgresToolTable.SEARCH_DOC: "documents",
}


def _table_filters(args: PostgresQueryArgs) -> dict[str, Any]:
    """The parsed filter kwargs for the table — field names match the DB-layer
    query function parameters exactly."""
    return args.model_dump(include=set(_FILTER_FIELDS_BY_TABLE[args.table]))


def _reject(message: str) -> ToolCallException:
    return ToolCallException(
        message=f"postgres_query rejected: {message}",
        llm_facing_message=message,
    )


def _parse_date(field: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise _reject(f"'{field}' must be an ISO date/datetime string.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _reject(
            f"'{field}' is not a valid ISO date/datetime: {value!r}. "
            f"Use e.g. '2026-06-01' or '2026-06-01T12:00:00Z'."
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_filter_value(field: str, value: Any) -> Any:
    if field in _DATE_FIELDS:
        return _parse_date(field, value)
    if field == "source_type":
        try:
            return DocumentSource(value)
        except ValueError:
            raise _reject(
                f"Invalid source_type {value!r}. Use the connector source id, "
                f"e.g. 'confluence', 'google_drive', 'slack', 'jira', 'web'."
            )
    if field == "node_type":
        try:
            return HierarchyNodeType(value)
        except ValueError:
            raise _reject(
                f"Invalid node_type {value!r}. "
                f"Examples: 'folder', 'shared_drive', 'source'."
            )
    if field == "message_type":
        if value not in (MessageType.USER.value, MessageType.ASSISTANT.value):
            raise _reject("'message_type' must be 'user' or 'assistant'.")
        return MessageType(value)
    if field == "chat_session_id":
        try:
            return UUID(str(value))
        except ValueError:
            raise _reject(f"'chat_session_id' must be a UUID. Got: {value!r}.")
    if field == "cited_only":
        if not isinstance(value, bool):
            raise _reject("'cited_only' must be a boolean.")
        return value
    if field in ("parent_hierarchy_node_id", "parent_id", "chat_message_id"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise _reject(f"'{field}' must be an integer.")
        return value
    if not isinstance(value, str):
        raise _reject(f"'{field}' must be a string.")
    return value


def _parse_any_of(field: str, value: Any) -> list[Any]:
    """One value or a list of values, deduplicated in order."""
    values = value if isinstance(value, list) else [value]
    if not values:
        raise _reject(f"'{field}' must not be an empty list.")
    if len(values) > _MAX_ANY_OF_VALUES:
        raise _reject(
            f"'{field}' takes at most {_MAX_ANY_OF_VALUES} values. Split the "
            "query or narrow the list."
        )
    parsed = [_parse_filter_value(field, item) for item in values]
    return list(dict.fromkeys(parsed))


def _validate_document_content_filter(
    phrases: list[str], group_by: str | None, order_by: DocumentOrder
) -> None:
    if not CONTENT_FILTER_AVAILABLE:
        raise _reject(
            "'content_contains' is not available for documents on this "
            "deployment. Use search to find documents by what they say."
        )
    if group_by is not None:
        raise _reject(
            "'group_by' does not work with a document content_contains filter."
        )
    if date_field_for_order(order_by) is None:
        raise _reject(
            "Document listings with content_contains order by date only: use "
            "'updated_desc', 'updated_asc', 'created_desc' or 'created_asc'."
        )
    for phrase in phrases:
        if not phrase.strip():
            raise _reject("'content_contains' values must not be blank.")
        if len(phrase) > _MAX_CONTENT_PHRASE_CHARS:
            raise _reject(
                f"'content_contains' values for documents take at most "
                f"{_MAX_CONTENT_PHRASE_CHARS} characters. Use a shorter phrase."
            )


def _parse_args(llm_kwargs: dict[str, Any]) -> PostgresQueryArgs:
    all_filter_fields = frozenset().union(*_FILTER_FIELDS_BY_TABLE.values())

    unknown = set(llm_kwargs) - _GENERAL_FIELDS - all_filter_fields
    if unknown:
        raise _reject(f"Unknown field(s): {sorted(unknown)}.")

    raw_table = llm_kwargs.get("table")
    try:
        table = PostgresToolTable(raw_table)
    except ValueError:
        raise _reject(
            f"'table' is required and must be one of: "
            f"{[t.value for t in PostgresToolTable]}. Got: {raw_table!r}."
        )

    allowed = _FILTER_FIELDS_BY_TABLE[table]
    misapplied = (set(llm_kwargs) & all_filter_fields) - allowed
    if misapplied:
        raise _reject(
            f"Field(s) {sorted(misapplied)} do not apply to table "
            f"'{table.value}'. Valid filters for '{table.value}': {sorted(allowed)}."
        )

    count = llm_kwargs.get("count", False)
    if not isinstance(count, bool):
        raise _reject("'count' must be a boolean.")

    group_by = llm_kwargs.get("group_by")
    if group_by is not None:
        if not count:
            raise _reject("'group_by' requires count=true.")
        valid_groups = _GROUP_BY_BY_TABLE.get(table, frozenset())
        if group_by not in valid_groups:
            raise _reject(
                f"'group_by' value {group_by!r} is not valid for table "
                f"'{table.value}'. Valid values: {sorted(valid_groups) or 'none'}."
            )

    cursor = llm_kwargs.get("cursor")
    if cursor is not None:
        if table != PostgresToolTable.DOCUMENT or count:
            raise _reject("'cursor' applies only to document listings (count=false).")
        if not isinstance(cursor, str):
            raise _reject(
                "'cursor' must be the next_cursor string from a previous page."
            )

    order_by = DocumentOrder.UPDATED_DESC
    if "order_by" in llm_kwargs:
        if table != PostgresToolTable.DOCUMENT or count:
            raise _reject("'order_by' applies only to document listings (count=false).")
        try:
            order_by = DocumentOrder(llm_kwargs["order_by"])
        except ValueError:
            raise _reject(
                f"Invalid order_by {llm_kwargs['order_by']!r}. Valid values: "
                f"{[o.value for o in DocumentOrder]}."
            )

    limit = llm_kwargs.get("limit", POSTGRES_TOOL_DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise _reject("'limit' must be an integer.")
    if limit < 1:
        raise _reject("'limit' must be at least 1.")

    parsed: dict[str, Any] = {
        "table": table,
        "count": count,
        "group_by": group_by,
        "limit": limit,
        "cursor": cursor,
        "order_by": order_by,
    }

    for field in set(llm_kwargs) & allowed:
        value = llm_kwargs[field]
        parsed[field] = (
            _parse_any_of(field, value)
            if field in _ANY_OF_FIELDS
            else _parse_filter_value(field, value)
        )

    if table == PostgresToolTable.DOCUMENT and "content_contains" in parsed:
        _validate_document_content_filter(
            parsed["content_contains"], group_by, order_by
        )

    if table == PostgresToolTable.SEARCH_DOC and parsed.get("chat_message_id") is None:
        raise _reject(
            "Table 'search_doc' requires 'chat_message_id' — the past chat "
            "message whose sources you want. Find it with a chat_message query."
        )

    return PostgresQueryArgs(**parsed)


# ============================== Cursors ==============================

_INVALID_CURSOR_MESSAGE = (
    "'cursor' is not a valid next_cursor value. Start again without a cursor."
)


def _document_query_key(args: PostgresQueryArgs, scope: DocumentScope) -> str:
    """Identifies the filters and scope that a cursor belongs to."""
    filters = _table_filters(args)
    # Cursors issued before documents took content_contains have no such key.
    if filters.get("content_contains") is None:
        filters.pop("content_contains", None)
    query = {
        "filters": filters,
        "order_by": args.order_by.value,
        "scope": scope.model_dump(mode="json"),
    }
    encoded = json.dumps(query, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _encode_cursor(
    cursor: DocumentCursor, query_key: str, content_path: ContentPath | None = None
) -> str:
    value = cursor.sort_value
    payload = {
        "u": value.isoformat() if isinstance(value, datetime) else value,
        "i": cursor.document_id,
        "q": query_key,
    }
    if content_path is not None:
        payload["p"] = content_path.value
    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return token.rstrip("=")


def _decode_cursor(token: str, query_key: str, order: DocumentOrder) -> DocumentCursor:
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        value = payload["u"]
        if value is not None and order.is_date:
            value = datetime.fromisoformat(value)
        elif value is not None and not isinstance(value, str):
            raise TypeError("A title cursor value must be a string.")
        cursor = DocumentCursor(sort_value=value, document_id=payload["i"])
        cursor_query_key = payload["q"]
    except (ValueError, TypeError, KeyError) as e:
        raise _reject(_INVALID_CURSOR_MESSAGE) from e
    if cursor_query_key != query_key:
        raise _reject(
            "This cursor belongs to a query with different filters. Use the "
            "same filters as the call that returned it, or start again "
            "without a cursor."
        )
    return cursor


def _decode_content_cursor(
    token: str, query_key: str, order: DocumentOrder
) -> ContentCursor:
    cursor = _decode_cursor(token, query_key, order)
    try:
        padded = token + "=" * (-len(token) % 4)
        path = ContentPath(json.loads(base64.urlsafe_b64decode(padded.encode()))["p"])
    except (ValueError, KeyError) as e:
        raise _reject(_INVALID_CURSOR_MESSAGE) from e
    if isinstance(cursor.sort_value, str):
        raise _reject(_INVALID_CURSOR_MESSAGE)
    return ContentCursor(
        path=path, sort_value=cursor.sort_value, document_id=cursor.document_id
    )


# ============================ Row formatting ============================


def _date_or_unknown(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value is not None else "unknown"


def _document_to_search_doc(doc: Document, source: DocumentSource) -> SearchDoc:
    # Metadata-only: the tool never reads content, so there is no blurb.
    return SearchDoc(
        document_id=doc.id,
        chunk_ind=0,
        semantic_identifier=doc.semantic_id,
        link=doc.link,
        blurb="",
        source_type=source,
        # Nothing is ranked; the chat sidebar hides documents without a score.
        score=0.0,
        boost=doc.boost,
        hidden=doc.hidden,
        metadata={},
        match_highlights=[],
        updated_at=doc.doc_updated_at,
        primary_owners=doc.primary_owners,
        secondary_owners=doc.secondary_owners,
    )


def _format_citable_row(doc: SearchDoc, citation_num: int) -> str:
    owners = ", ".join(doc.primary_owners or []) or "-"
    return (
        f"- [{citation_num}] {doc.semantic_identifier} | id={doc.document_id} | "
        f"source={doc.source_type.value} | "
        f"updated={_date_or_unknown(doc.updated_at)} | "
        f"owners={owners} | link={doc.link or '-'}"
    )


def _assign_citation_numbers(
    docs: list[SearchDoc], context: ToolContext, call_index: int
) -> dict[int, str]:
    """Citation number -> document id. Docs already cited in the conversation
    keep their number; new docs draw from this call's reserved block."""
    existing = {doc_id: num for num, doc_id in context.citation_mapping.items()}
    next_num = context.next_citation_num + CITATIONS_PER_TOOL_CALL * call_index
    mapping: dict[int, str] = {}
    for doc in docs:
        num = existing.get(doc.document_id)
        if num is None:
            num = next_num
            next_num += 1
        mapping[num] = doc.document_id
    return mapping


def _citable_rows_result(
    docs: list[SearchDoc],
    render: Callable[[list[str]], str],
    context: ToolContext,
    call_index: int,
) -> ToolResult:
    """`render` turns the numbered rows into the result text."""
    citation_mapping = _assign_citation_numbers(docs, context, call_index)
    num_by_doc_id = {doc_id: num for num, doc_id in citation_mapping.items()}
    content = render(
        [_format_citable_row(d, num_by_doc_id[d.document_id]) for d in docs]
    )
    return ToolResult(
        content=content,
        details=SearchDocsResponse(search_docs=docs, citation_mapping=citation_mapping),
    )


def _format_hierarchy_node_row(node: HierarchyNode) -> str:
    return (
        f"- {node.display_name} | id={node.id} | type={node.node_type.value} | "
        f"source={node.source.value} | parent_id={node.parent_id} | "
        f"link={node.link or '-'}"
    )


def _format_chat_session_row(session: ChatSession) -> str:
    return (
        f"- {session.description or 'Untitled'} | "
        f"created={_date_or_unknown(session.time_created)} | "
        f"link=/chat/{session.id}"
    )


def _format_chat_message_row(message: ChatMessage) -> str:
    snippet = " ".join(message.message.split())
    if len(snippet) > _MESSAGE_SNIPPET_CHARS:
        snippet = snippet[:_MESSAGE_SNIPPET_CHARS] + "…"
    return (
        f"- [{message.message_type.value}] {snippet} | "
        f"message_id={message.id} | sent={_date_or_unknown(message.time_sent)} | "
        f"session_link=/chat/{message.chat_session_id}"
    )


def _format_count(count: int, noun: str) -> str:
    return f"{count} matching {noun}."


def _format_group_counts(groups: list[GroupCount], noun: str, group_by: str) -> str:
    if not groups and group_by == DocumentGroupBy.OWNER.value:
        # Owner groups leave out documents with no recorded owner.
        return (
            f"No matching {noun} have a recorded owner. Use count=true without "
            f"group_by for the total."
        )
    if not groups:
        return f"0 matching {noun}."
    header = f"Matching {noun} by {group_by}:"
    if len(groups) > POSTGRES_TOOL_MAX_LIMIT:
        groups = groups[:POSTGRES_TOOL_MAX_LIMIT]
        header = (
            f"Matching {noun} by {group_by}, top {POSTGRES_TOOL_MAX_LIMIT} groups "
            f"(there are more; narrow the filters to see the rest):"
        )
    lines = [f"{g.group}: {g.count}" for g in groups]
    return header + "\n" + "\n".join(lines)


_ORDER_LABELS: dict[DocumentOrder, str] = {
    DocumentOrder.UPDATED_DESC: "newest first",
    DocumentOrder.UPDATED_ASC: "oldest first",
    DocumentOrder.CREATED_DESC: "newest created first",
    DocumentOrder.CREATED_ASC: "oldest created first",
    DocumentOrder.TITLE_ASC: "by title A-Z",
    DocumentOrder.TITLE_DESC: "by title Z-A",
}


def _format_document_page(
    lines: list[str],
    *,
    total: int | None,
    continued: bool,
    next_cursor: str | None,
    order: DocumentOrder,
) -> str:
    """`total` is set on a first page that has more pages after it, when the
    count finished in time."""
    if not lines:
        if continued:
            return "No more matching documents."
        return "0 matching documents. Consider broadening the filters."
    if next_cursor is None:
        header = (
            f"The last {len(lines)} matching documents:"
            if continued
            else f"{len(lines)} matching documents:"
        )
        return header + "\n" + "\n".join(lines)
    label = _ORDER_LABELS[order]
    if continued:
        header = f"The next {len(lines)} matching documents, {label}:"
    elif total is None:
        header = (
            f"The first {len(lines)} matching documents, {label} (more match; "
            "use count=true for the total):"
        )
    else:
        header = f"Showing {len(lines)} of {total} matching documents, {label}:"
    footer = (
        "More documents match. To get the next page, call again with the same "
        "filters, order_by and cursor set to this next_cursor value.\n"
        f"next_cursor: {next_cursor}"
    )
    return header + "\n" + "\n".join(lines) + "\n" + footer


def _format_rows(lines: list[str], noun: str, effective_limit: int) -> str:
    if not lines:
        return f"0 matching {noun}. Consider broadening the filters."
    header = f"{len(lines)} matching {noun}:"
    if len(lines) >= effective_limit:
        header = (
            f"Showing {len(lines)} matching {noun} (result capped at "
            f"{effective_limit} — there may be more; narrow the filters or "
            f"use count=true for the exact total):"
        )
    return header + "\n" + "\n".join(lines)


class PostgresTool(Tool):
    rank = ToolRank.POSTGRES_QUERY
    NAME = POSTGRES_TOOL_NAME
    DISPLAY_NAME = "Knowledge Base Query"
    DESCRIPTION = (
        "Run an exact, structured query over Onyx's metadata tables instead of "
        "semantic search. Use it to count or exhaustively list documents by "
        "metadata (source, title substring, update date, owner, folder), to "
        "browse source folder structure, to find the user's past conversations "
        "or messages, and to look up which documents a past answer cited. With "
        "content_contains it also lists or counts every document whose text "
        "contains a phrase; that is slow, so use it only for exhaustive "
        "listings or counts by content. For questions about what documents "
        "say, use search. Results are permission-scoped to the current user. Document "
        "listings come in pages: pass each page's next_cursor back as cursor "
        "to go through every matching document."
    )

    # Built per turn with internal search; it has no tool row.
    id = None

    def __init__(
        self,
        user: User,
        current_chat_session_id: UUID | None,
        scope: DocumentScope,
    ) -> None:
        self._user = user
        # The agent's search knowledge, applied to documents and folders.
        self._scope = scope
        # The in-flight conversation: excluded from chat-history queries, which
        # would otherwise top-hit the question the user just asked.
        self._current_chat_session_id = current_chat_session_id

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _CODE_MODE_RESULT

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": _PARAMETER_SCHEMA,
                "required": ["table"],
            },
        )

    @override
    def _run(
        self,
        invocation: ToolInvocation,
        context: ToolContext,
    ) -> ToolResult:
        args = _parse_args(dict(invocation.arguments))
        # Every anonymous visitor shares one user row, so ownership scoping
        # cannot separate their chat histories.
        if self._user.is_anonymous and args.table in CHAT_HISTORY_TABLES:
            raise _reject(
                "Chat history is unavailable to anonymous users. Only the "
                "'document' and 'hierarchy_node' tables can be queried."
            )

        try:
            with (
                get_session_with_current_tenant() as db_session,
                tool_transaction(db_session),
            ):
                return self._execute(db_session, args, context, invocation.call_index)
        except PostgresToolQueryTimeoutError as e:
            raise ToolCallException(
                message=f"postgres_query timed out: {e}",
                llm_facing_message=(
                    "The query timed out — it scanned too much data. Narrow "
                    "the filters (add a substring, date range, or source "
                    "filter) or use count=true."
                ),
            ) from e

    def _execute(
        self,
        db_session: Session,
        args: PostgresQueryArgs,
        context: ToolContext,
        call_index: int,
    ) -> ToolResult:
        noun = _NOUN_BY_TABLE[args.table]

        if args.table in _SCOPED_TABLES:
            if self._scope.source_types == []:
                return ToolResult(content=_NO_SOURCES_MESSAGE)
            if self._scope.matches_no_documents:
                return ToolResult(content=_USER_FILES_ONLY_MESSAGE)
            result = self._execute_scoped(db_session, args, noun, context, call_index)
            if self._scope.is_unrestricted:
                return result
            return result.model_copy(
                update={"content": f"{_SCOPE_NOTE}\n{result.content}"}
            )
        if args.table == PostgresToolTable.SEARCH_DOC:
            return self._execute_search_doc(db_session, args, context, call_index)

        exclude_id = self._current_chat_session_id
        if args.table == PostgresToolTable.CHAT_SESSION:
            return ToolResult(
                content=self._execute_chat_session(db_session, args, noun, exclude_id)
            )
        return ToolResult(
            content=self._execute_chat_message(db_session, args, noun, exclude_id)
        )

    def _execute_scoped(
        self,
        db_session: Session,
        args: PostgresQueryArgs,
        noun: str,
        context: ToolContext,
        call_index: int,
    ) -> ToolResult:
        if args.table == PostgresToolTable.DOCUMENT:
            return self._execute_document(db_session, args, noun, context, call_index)
        return ToolResult(content=self._execute_hierarchy_node(db_session, args, noun))

    def _execute_document(
        self,
        db_session: Session,
        args: PostgresQueryArgs,
        noun: str,
        context: ToolContext,
        call_index: int,
    ) -> ToolResult:
        user_email = self._user.email
        external_group_ids = get_user_external_group_ids(db_session, self._user)
        table_filters = _table_filters(args)
        phrases: list[str] | None = table_filters.pop("content_contains")
        if phrases is not None:
            return self._execute_document_content(
                db_session,
                args,
                phrases,
                table_filters,
                external_group_ids,
                context,
                call_index,
            )
        filters: dict[str, Any] = {**table_filters, "scope": self._scope}
        if args.count and args.group_by is not None:
            groups = count_documents_grouped_for_tool(
                db_session,
                user_email,
                external_group_ids,
                DocumentGroupBy(args.group_by),
                user_id=self._user.id,
                prior_emails=self._user.prior_emails,
                **filters,
            )
            return ToolResult(content=_format_group_counts(groups, noun, args.group_by))
        if args.count:
            return ToolResult(
                content=_format_count(
                    count_documents_for_tool(
                        db_session,
                        user_email,
                        external_group_ids,
                        user_id=self._user.id,
                        prior_emails=self._user.prior_emails,
                        **filters,
                    ),
                    noun,
                )
            )
        query_key = _document_query_key(args, self._scope)
        after = (
            _decode_cursor(args.cursor, query_key, args.order_by)
            if args.cursor is not None
            else None
        )
        page = query_documents_for_tool(
            db_session,
            user_email,
            external_group_ids,
            user_id=self._user.id,
            prior_emails=self._user.prior_emails,
            order=args.order_by,
            after=after,
            limit=args.limit,
            **filters,
        )
        total = None
        if after is None and page.next_cursor is not None:
            total = try_count_documents_for_tool(
                db_session,
                user_email,
                external_group_ids,
                user_id=self._user.id,
                prior_emails=self._user.prior_emails,
                **filters,
            )
        next_cursor = (
            _encode_cursor(page.next_cursor, query_key)
            if page.next_cursor is not None
            else None
        )
        return _citable_rows_result(
            [_document_to_search_doc(doc, source) for doc, source in page.rows],
            lambda lines: _format_document_page(
                lines,
                total=total,
                continued=after is not None,
                next_cursor=next_cursor,
                order=args.order_by,
            ),
            context,
            call_index,
        )

    def _execute_document_content(
        self,
        db_session: Session,
        args: PostgresQueryArgs,
        phrases: list[str],
        filters: dict[str, Any],
        external_group_ids: list[str],
        context: ToolContext,
        call_index: int,
    ) -> ToolResult:
        document_index = get_default_document_index(
            get_current_search_settings(db_session), None
        )
        # Built first: its time budget covers the phrase checks too.
        content_filter = ContentFilter(
            db_session=db_session,
            document_index=document_index,
            user=self._user,
            external_group_ids=external_group_ids,
            filters=filters,
            scope=self._scope,
            phrases=phrases,
        )
        for phrase in phrases:
            if document_index.count_phrase_terms(phrase) == 0:
                raise _reject(
                    f"'content_contains' value {phrase!r} has no searchable words "
                    "(only common words such as 'the' or 'and'). Use a more "
                    "specific phrase."
                )
        if args.count:
            count = content_filter.count()
            if count.is_complete:
                return ToolResult(content=_format_count(count.count, "documents"))
            return ToolResult(
                content=(
                    f"At least {count.count} matching documents. Counting by "
                    f"content stops at {MAX_COUNT} documents or when it takes "
                    "too long; add date, source or folder filters for an exact count."
                )
            )
        query_key = _document_query_key(args, self._scope)
        after = (
            _decode_content_cursor(args.cursor, query_key, args.order_by)
            if args.cursor is not None
            else None
        )
        page = content_filter.list_page(args.order_by, after, args.limit)
        next_cursor = (
            _encode_cursor(
                DocumentCursor(
                    sort_value=page.next_cursor.sort_value,
                    document_id=page.next_cursor.document_id,
                ),
                query_key,
                page.next_cursor.path,
            )
            if page.next_cursor is not None
            else None
        )

        def _format(lines: list[str]) -> str:
            if page.is_partial and not lines:
                return (
                    "No matches yet: matching by content took too long to search "
                    "further. More documents may match. Call again with the same "
                    "filters and cursor set to this next_cursor value, or add "
                    f"date, source or folder filters.\nnext_cursor: {next_cursor}"
                )
            text = _format_document_page(
                lines,
                total=None,
                continued=after is not None,
                next_cursor=next_cursor,
                order=args.order_by,
            )
            if not page.is_partial:
                return text
            return (
                "Matching by content took too long to fill this page, so it may "
                "show fewer documents than asked for. Continue with the cursor "
                "below, or add date, source or folder filters.\n" + text
            )

        return _citable_rows_result(
            [_document_to_search_doc(doc, source) for doc, source in page.rows],
            _format,
            context,
            call_index,
        )

    def _execute_hierarchy_node(
        self, db_session: Session, args: PostgresQueryArgs, noun: str
    ) -> str:
        user_email = self._user.email
        external_group_ids = get_user_external_group_ids(db_session, self._user)
        filters: dict[str, Any] = {**_table_filters(args), "scope": self._scope}
        if args.count:
            return _format_count(
                count_hierarchy_nodes_for_tool(
                    db_session,
                    user_email,
                    external_group_ids,
                    user_id=self._user.id,
                    **filters,
                ),
                noun,
            )
        nodes = query_hierarchy_nodes_for_tool(
            db_session,
            user_email,
            external_group_ids,
            user_id=self._user.id,
            limit=args.limit,
            **filters,
        )
        return _format_rows(
            [_format_hierarchy_node_row(n) for n in nodes],
            noun,
            min(args.limit, POSTGRES_TOOL_MAX_LIMIT),
        )

    def _execute_chat_session(
        self,
        db_session: Session,
        args: PostgresQueryArgs,
        noun: str,
        exclude_id: UUID | None,
    ) -> str:
        filters: dict[str, Any] = {
            **_table_filters(args),
            "exclude_chat_session_id": exclude_id,
        }
        if args.count and args.group_by is not None:
            groups = count_chat_sessions_by_month_for_tool(
                db_session, self._user.id, **filters
            )
            return _format_group_counts(groups, noun, args.group_by)
        if args.count:
            return _format_count(
                count_chat_sessions_for_tool(db_session, self._user.id, **filters),
                noun,
            )
        sessions = query_chat_sessions_for_tool(
            db_session, self._user.id, limit=args.limit, **filters
        )
        return _format_rows(
            [_format_chat_session_row(s) for s in sessions],
            noun,
            min(args.limit, POSTGRES_TOOL_MAX_LIMIT),
        )

    def _execute_chat_message(
        self,
        db_session: Session,
        args: PostgresQueryArgs,
        noun: str,
        exclude_id: UUID | None,
    ) -> str:
        filters: dict[str, Any] = {
            **_table_filters(args),
            "exclude_chat_session_id": exclude_id,
        }
        if args.count and args.group_by is not None:
            groups = count_chat_messages_by_month_for_tool(
                db_session, self._user.id, **filters
            )
            return _format_group_counts(groups, noun, args.group_by)
        if args.count:
            return _format_count(
                count_chat_messages_for_tool(db_session, self._user.id, **filters),
                noun,
            )
        messages = query_chat_messages_for_tool(
            db_session, self._user.id, limit=args.limit, **filters
        )
        return _format_rows(
            [_format_chat_message_row(m) for m in messages],
            noun,
            min(args.limit, POSTGRES_TOOL_MAX_LIMIT),
        )

    def _execute_search_doc(
        self,
        db_session: Session,
        args: PostgresQueryArgs,
        context: ToolContext,
        call_index: int,
    ) -> ToolResult:
        chat_message_id = args.chat_message_id
        if chat_message_id is None:
            raise _reject("Table 'search_doc' requires 'chat_message_id'.")
        noun = "cited documents" if args.cited_only else "retrieved documents"
        if args.count:
            return ToolResult(
                content=_format_count(
                    count_search_docs_for_tool(
                        db_session,
                        self._user.id,
                        chat_message_id,
                        cited_only=args.cited_only,
                    ),
                    noun,
                )
            )
        db_docs = query_search_docs_for_tool(
            db_session,
            self._user.id,
            chat_message_id,
            cited_only=args.cited_only,
            limit=args.limit,
        )
        if not db_docs:
            return ToolResult(
                content=(
                    f"No {noun} for chat message {chat_message_id}. The "
                    f"message may not exist, may not be yours, or cited nothing."
                )
            )
        return _citable_rows_result(
            [translate_db_search_doc_to_saved_search_doc(d) for d in db_docs],
            lambda lines: _format_rows(
                lines, noun, min(args.limit, POSTGRES_TOOL_MAX_LIMIT)
            ),
            context,
            call_index,
        )
