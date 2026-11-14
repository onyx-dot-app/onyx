"""Postgres query tool: structured, ACL-safe queries over a small allowlist
of metadata tables, as an alternative to semantic search for questions about
metadata, counting, structure, or the user's own chat history.

The LLM supplies fully-typed filter arguments (no NL-to-filter translation, so
`run()` makes no LLM call). All queries go through the restricted query layer
in `onyx.db.postgres_tool`, which enforces per-table access control, row caps,
and a statement timeout.
"""

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
)
from onyx.db.postgres_tool_models import GroupCount
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.constants import POSTGRES_TOOL_NAME
from onyx.tools.interface import CITATIONS_PER_TOOL_CALL, Tool
from onyx.tools.models import CodeModeExposure, ToolCallException, ToolContext
from onyx.tools.tool_implementations.postgres.models import (
    PostgresQueryArgs,
    PostgresToolTable,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MESSAGE_SNIPPET_CHARS = 300


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

_GENERAL_FIELDS = frozenset({"table", "count", "group_by", "limit"})


def _prop(
    json_type: str, description: str, enum: list[str] | None = None
) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": json_type, "description": description}
    if enum is not None:
        prop["enum"] = enum
    return prop


# fmt: off
_PARAMETER_SCHEMA: dict[str, dict[str, Any]] = {
    "table": _prop("string", "Which table to query.", [t.value for t in PostgresToolTable]),
    "count": _prop("boolean", "Return only the number of matching rows (default false)."),
    "group_by": _prop("string", "Only with count=true: break the count down. document: 'source' or 'owner'; chat_session/chat_message: 'month'.", ["source", "owner", "month"]),
    "limit": _prop("integer", f"Max rows to return (default {POSTGRES_TOOL_DEFAULT_LIMIT}, max {POSTGRES_TOOL_MAX_LIMIT})."),
    "source_type": _prop("string", "document/hierarchy_node: connector source id, e.g. 'confluence', 'google_drive', 'slack', 'web'."),
    "title_contains": _prop("string", "document: case-insensitive title substring, matched literally (% and _ are not wildcards; do not escape them)."),
    "updated_after": _prop("string", "document: ISO date lower bound on when the doc changed at its source. Docs with unknown source timestamps never match date filters."),
    "updated_before": _prop("string", "document: ISO date upper bound, exclusive (use the next day's date to include a whole day)."),
    "owned_by": _prop("string", "document: owner exactly as shown in a row's owners= field (usually a display name, sometimes an email; exact match). group_by=owner lists the stored values."),
    "parent_hierarchy_node_id": _prop("integer", "document: only docs directly inside this folder/space node."),
    "name_contains": _prop("string", "hierarchy_node: case-insensitive name substring."),
    "parent_id": _prop("integer", "hierarchy_node: list child nodes of this node."),
    "node_type": _prop("string", "hierarchy_node: e.g. 'folder', 'shared_drive', 'source'."),
    "description_contains": _prop("string", "chat_session: case-insensitive substring of the conversation title."),
    "created_after": _prop("string", "chat_session: ISO date lower bound."),
    "created_before": _prop("string", "chat_session: ISO date upper bound, exclusive."),
    "chat_session_id": _prop("string", "chat_message: only messages in this session (UUID)."),
    "content_contains": _prop("string", "chat_message: case-insensitive substring of the message text."),
    "message_type": _prop("string", "chat_message: filter by author.", ["user", "assistant"]),
    "sent_after": _prop("string", "chat_message: ISO date lower bound."),
    "sent_before": _prop("string", "chat_message: ISO date upper bound, exclusive."),
    "chat_message_id": _prop("integer", "search_doc (required): the past chat message whose sources to fetch."),
    "cited_only": _prop("boolean", "search_doc: true (default) = only docs the answer actually cited, in citation order; false = everything retrieved."),
}
# fmt: on

_CHAT_HISTORY_TABLES = frozenset(
    {
        PostgresToolTable.CHAT_SESSION,
        PostgresToolTable.CHAT_MESSAGE,
        PostgresToolTable.SEARCH_DOC,
    }
)

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
    }

    for field in set(llm_kwargs) & allowed:
        parsed[field] = _parse_filter_value(field, llm_kwargs[field])

    if table == PostgresToolTable.SEARCH_DOC and parsed.get("chat_message_id") is None:
        raise _reject(
            "Table 'search_doc' requires 'chat_message_id' — the past chat "
            "message whose sources you want. Find it with a chat_message query."
        )

    return PostgresQueryArgs(**parsed)


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
    noun: str,
    limit: int,
    context: ToolContext,
    call_index: int,
) -> ToolResult:
    citation_mapping = _assign_citation_numbers(docs, context, call_index)
    num_by_doc_id = {doc_id: num for num, doc_id in citation_mapping.items()}
    content = _format_rows(
        [_format_citable_row(d, num_by_doc_id[d.document_id]) for d in docs],
        noun,
        min(limit, POSTGRES_TOOL_MAX_LIMIT),
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
    NAME = POSTGRES_TOOL_NAME
    DISPLAY_NAME = "Knowledge Base Query"
    DESCRIPTION = (
        "Run an exact, structured query over Onyx's metadata tables instead of "
        "semantic search. Use it to count or exhaustively list documents by "
        "metadata (source, title substring, update date, owner, folder), to "
        "browse source folder structure, to find the user's past conversations "
        "or messages, and to look up which documents a past answer cited. Not "
        "for questions about document content or meaning — use search for "
        "those. Results are permission-scoped to the current user."
    )

    def __init__(
        self,
        tool_id: int,
        user: User,
        current_chat_session_id: UUID | None,
    ) -> None:
        self._id = tool_id
        self._user = user
        # The in-flight conversation: excluded from chat-history queries, which
        # would otherwise top-hit the question the user just asked.
        self._current_chat_session_id = current_chat_session_id

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    @property
    def id(self) -> int:
        return self._id

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
        if self._user.is_anonymous and args.table in _CHAT_HISTORY_TABLES:
            raise _reject(
                "Chat history is unavailable to anonymous users. Only the "
                "'document' and 'hierarchy_node' tables can be queried."
            )

        try:
            with get_session_with_current_tenant() as db_session:
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

        if args.table == PostgresToolTable.DOCUMENT:
            return self._execute_document(db_session, args, noun, context, call_index)
        if args.table == PostgresToolTable.SEARCH_DOC:
            return self._execute_search_doc(db_session, args, context, call_index)
        if args.table == PostgresToolTable.HIERARCHY_NODE:
            return ToolResult(
                content=self._execute_hierarchy_node(db_session, args, noun)
            )

        exclude_id = self._current_chat_session_id
        if args.table == PostgresToolTable.CHAT_SESSION:
            return ToolResult(
                content=self._execute_chat_session(db_session, args, noun, exclude_id)
            )
        return ToolResult(
            content=self._execute_chat_message(db_session, args, noun, exclude_id)
        )

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
        filters = _table_filters(args)
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
        rows = query_documents_for_tool(
            db_session,
            user_email,
            external_group_ids,
            user_id=self._user.id,
            prior_emails=self._user.prior_emails,
            limit=args.limit,
            **filters,
        )
        return _citable_rows_result(
            [_document_to_search_doc(doc, source) for doc, source in rows],
            noun,
            args.limit,
            context,
            call_index,
        )

    def _execute_hierarchy_node(
        self, db_session: Session, args: PostgresQueryArgs, noun: str
    ) -> str:
        user_email = self._user.email
        external_group_ids = get_user_external_group_ids(db_session, self._user)
        filters = _table_filters(args)
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
            noun,
            args.limit,
            context,
            call_index,
        )
