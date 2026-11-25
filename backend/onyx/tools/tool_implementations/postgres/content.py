"""postgres_query's document content filter: documents whose text contains
any of the given phrases, listed or counted exhaustively.

Postgres applies the metadata filters and OpenSearch matches the text, in one
of two ways that give the same documents in the same order:

- OpenSearch first, by default: OpenSearch pages the text matches with every
  filter it can apply. Postgres then applies the other filters and checks
  access again.
- Postgres first, when a filter that only Postgres applies (title, owner,
  folder) leaves few candidates: Postgres pages the candidates in the
  requested order and OpenSearch checks each batch for the text. Otherwise
  OpenSearch would page through every text match only for Postgres to drop
  most of them.

The sizes come from a benchmark on a deployment with 1.2M documents and on
a synthetic 1M-document index. An OpenSearch page of 100 matches took
10-65 ms and of 500 about 20 ms; checking 100 matches in Postgres took about
10 ms; a Postgres candidate batch took 70 ms-1.1 s whatever its size; an
exact count of 20,000 matches took 0.4 s.

POSTGRES_QUERY_CONTENT_FIRST overrides the choice for every call.

Sources that censor records at read time (Salesforce) match only under a
public connector, where search does not censor them either: elsewhere a phrase
in a record the caller cannot read would still match its document.

A listing keeps the way of its first page, so that its cursor stays valid.
"""

import time
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.chat_configs import (
    DISABLE_POSTGRES_QUERY_CONTENT_FILTER,
    POSTGRES_QUERY_CONTENT_FIRST,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.db.models import Document, User
from onyx.db.postgres_tool import (
    POSTGRES_TOOL_MAX_LIMIT,
    document_source_types,
    filter_document_ids_for_tool,
    hierarchy_node_own_document_ids,
    public_cc_pair_ids_for_sources,
    query_document_keys_for_tool,
    query_documents_for_tool,
    try_count_documents_for_tool,
)
from onyx.db.postgres_tool_models import DocumentCursor, DocumentOrder, DocumentScope
from onyx.document_index.interfaces import (
    ContentMatchCount,
    ContentMatchDateField,
    ContentMatchKey,
    ContentMatchRequest,
    DocumentIndex,
)
from onyx.document_index.opensearch.client import OpenSearchServerSideTimeout
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# At most this many candidates take the Postgres-first way.
MAX_POSTGRES_FIRST_CANDIDATES = 20_000
# Candidates that one OpenSearch request checks on the Postgres-first way.
CANDIDATE_BATCH_SIZE = 5_000
# Text matches that one OpenSearch request returns on the OpenSearch-first way.
MATCH_BATCH_SIZE = 500
# Work one call may do before it returns what it has, with a cursor.
TIME_BUDGET_S = 15.0
# Counting stops here and reports a lower bound.
MAX_COUNT = 50_000

# Filters that only Postgres applies. Without them, OpenSearch counts alone,
# trusting its own copy of the permissions as search does. That count can be
# a little higher than the listing: it includes the boundary second of a
# fractional date bound, uploaded files that have no document row, and
# documents whose index permissions are behind Postgres.
_POSTGRES_ONLY_FILTERS = ("title_contains", "owned_by", "parent_hierarchy_node_id")


class ContentPath(str, Enum):
    POSTGRES_FIRST = "postgres_first"
    OPENSEARCH_FIRST = "opensearch_first"


class ContentFirst(str, Enum):
    """The POSTGRES_QUERY_CONTENT_FIRST setting."""

    AUTO = "auto"
    POSTGRES = "postgres"
    OPENSEARCH = "opensearch"


def _load_content_first() -> ContentFirst | None:
    """None for an unknown value: the tool then refuses content filters, so a
    typo neither breaks imports nor silently means "auto"."""
    try:
        return ContentFirst(POSTGRES_QUERY_CONTENT_FIRST)
    except ValueError:
        logger.error(
            "Invalid POSTGRES_QUERY_CONTENT_FIRST %r: use auto, postgres or "
            "opensearch. postgres_query's document content filter is off.",
            POSTGRES_QUERY_CONTENT_FIRST,
        )
        return None


CONTENT_FIRST = _load_content_first()


def _content_filter_is_available() -> bool:
    """Whether this deployment can match document content: the document index
    is on, the filter is not turned off, and the setting is valid."""
    return (
        not DISABLE_VECTOR_DB
        and not DISABLE_POSTGRES_QUERY_CONTENT_FILTER
        and CONTENT_FIRST is not None
    )


CONTENT_FILTER_AVAILABLE = _content_filter_is_available()


def _censoring_sources() -> set[DocumentSource]:
    get_sources = fetch_ee_implementation_or_noop(
        "onyx.external_permissions.sync_params",
        "get_all_censoring_enabled_sources",
        noop_return_value=set(),
    )
    return get_sources()


class ContentCursor(BaseModel):
    """The position after which the next page starts, and the way of the
    listing."""

    path: ContentPath
    sort_value: datetime | None
    document_id: str


class ContentPage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    rows: list[tuple[Document, DocumentSource]]
    # Set when more documents may match after this page.
    next_cursor: ContentCursor | None
    # True when the time budget ran out before the page was full.
    is_partial: bool


def date_field_for_order(order: DocumentOrder) -> ContentMatchDateField | None:
    """The OpenSearch date for a listing order; None for the title orders,
    which OpenSearch cannot sort."""
    if order in (DocumentOrder.UPDATED_DESC, DocumentOrder.UPDATED_ASC):
        return ContentMatchDateField.UPDATED
    if order in (DocumentOrder.CREATED_DESC, DocumentOrder.CREATED_ASC):
        return ContentMatchDateField.CREATED
    return None


class ContentFilter:
    """Lists or counts the documents that match the metadata filters and
    contain any of the phrases, for one tool call."""

    def __init__(
        self,
        db_session: Session,
        document_index: DocumentIndex,
        user: User,
        external_group_ids: list[str],
        filters: dict[str, Any],
        scope: DocumentScope,
        phrases: list[str],
    ) -> None:
        self._db_session = db_session
        self._document_index = document_index
        self._user = user
        self._external_group_ids = external_group_ids
        self._deadline = time.monotonic() + TIME_BUDGET_S
        # The tool's document filter kwargs for the Postgres queries, with
        # the sources narrowed to those the scope allows.
        self._filters: dict[str, Any] = {
            **filters,
            "source_type": document_source_types(filters.get("source_type"), scope),
        }
        self._scope = scope
        self._phrases = phrases
        # Every match comes from OpenSearch, so this one check covers both
        # ways and every count.
        self._censoring_sources = sorted(_censoring_sources())
        self._uncensored_cc_pair_ids = (
            public_cc_pair_ids_for_sources(db_session, self._censoring_sources)
            if self._censoring_sources
            else []
        )
        access = build_access_filters_for_user(user, db_session)
        self._access_filters = IndexFilters(
            access_control_list=access.access_control_list,
            cc_pair_access=access.cc_pair_access,
            tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
        )

    def choose_path(self) -> ContentPath:
        if CONTENT_FIRST == ContentFirst.POSTGRES:
            return ContentPath.POSTGRES_FIRST
        if CONTENT_FIRST == ContentFirst.OPENSEARCH or not (
            self._has_postgres_only_filter()
        ):
            return ContentPath.OPENSEARCH_FIRST
        candidates = try_count_documents_for_tool(
            self._db_session,
            self._user.email,
            self._external_group_ids,
            user_id=self._user.id,
            prior_emails=self._user.prior_emails,
            scope=self._scope,
            **self._filters,
        )
        if candidates is not None and candidates <= MAX_POSTGRES_FIRST_CANDIDATES:
            return ContentPath.POSTGRES_FIRST
        return ContentPath.OPENSEARCH_FIRST

    def list_page(
        self,
        order: DocumentOrder,
        after: ContentCursor | None,
        limit: int,
    ) -> ContentPage:
        if self._no_source_can_match():
            return ContentPage(rows=[], next_cursor=None, is_partial=False)
        path = after.path if after is not None else self.choose_path()
        limit = max(1, min(limit, POSTGRES_TOOL_MAX_LIMIT))
        if path == ContentPath.POSTGRES_FIRST:
            keys, next_key, is_partial = self._match_postgres_first(
                order,
                (
                    DocumentCursor(
                        sort_value=after.sort_value, document_id=after.document_id
                    )
                    if after is not None
                    else None
                ),
                limit,
            )
        else:
            keys, next_key, is_partial = self._match_opensearch_first(
                order,
                (
                    ContentMatchKey(
                        document_id=after.document_id, date=after.sort_value
                    )
                    if after is not None
                    else None
                ),
                limit,
            )
        return ContentPage(
            rows=self._load_rows(keys, order),
            next_cursor=(
                ContentCursor(
                    path=path,
                    sort_value=next_key.sort_value,
                    document_id=next_key.document_id,
                )
                if next_key is not None
                else None
            ),
            is_partial=is_partial,
        )

    def count(self) -> ContentMatchCount:
        if self._no_source_can_match():
            return ContentMatchCount(count=0, is_complete=True)
        if self.choose_path() == ContentPath.POSTGRES_FIRST:
            return self._count_postgres_first()
        if self._has_postgres_only_filter():
            return self._count_opensearch_first_checked()
        return self._document_index.count_documents_by_content(
            self._opensearch_first_request(), MAX_COUNT, self._deadline
        )

    def _no_source_can_match(self) -> bool:
        # OpenSearch reads an empty source list as no source filter.
        return self._filters["source_type"] == []

    def _has_postgres_only_filter(self) -> bool:
        return any(
            self._filters.get(name) is not None for name in _POSTGRES_ONLY_FILTERS
        )

    def _out_of_time(self) -> bool:
        return time.monotonic() >= self._deadline

    def _postgres_kwargs(self) -> dict[str, Any]:
        return {
            "user_id": self._user.id,
            "prior_emails": self._user.prior_emails,
            "scope": self._scope,
            **self._filters,
        }

    def _candidates(
        self, order: DocumentOrder, after: DocumentCursor | None
    ) -> list[DocumentCursor]:
        return query_document_keys_for_tool(
            self._db_session,
            self._user.email,
            self._external_group_ids,
            order=order,
            after=after,
            limit=CANDIDATE_BATCH_SIZE,
            **self._postgres_kwargs(),
        )

    def _matching_candidates(self, candidates: list[DocumentCursor]) -> set[str]:
        """The candidates whose text matches. Postgres already applied the
        other filters, so OpenSearch only needs the permissions."""
        request = ContentMatchRequest(
            phrases=self._phrases,
            filters=self._access_filters,
            document_ids=[candidate.document_id for candidate in candidates],
            restricted_sources=self._censoring_sources,
            restricted_source_cc_pair_ids=self._uncensored_cc_pair_ids,
        )
        matches = self._document_index.match_documents_by_content(
            request, ContentMatchDateField.UPDATED, True, None, len(candidates)
        )
        return {match.document_id for match in matches}

    def _match_postgres_first(
        self, order: DocumentOrder, after: DocumentCursor | None, limit: int
    ) -> tuple[list[DocumentCursor], DocumentCursor | None, bool]:
        """Returns the page's documents, the position the next page starts
        after (None when no more match), and whether time ran out."""
        matched: list[DocumentCursor] = []
        position = after
        while True:
            candidates = self._candidates(order, position)
            try:
                matching = (
                    self._matching_candidates(candidates) if candidates else set()
                )
            except OpenSearchServerSideTimeout:
                # Keep the batches already checked; with none, the call fails.
                if position == after:
                    raise
                return matched, position, True
            for candidate in candidates:
                if candidate.document_id not in matching:
                    continue
                matched.append(candidate)
                # One match past the page shows that more exist.
                if len(matched) > limit:
                    return matched[:limit], matched[limit - 1], False
            if len(candidates) < CANDIDATE_BATCH_SIZE:
                return matched, None, False
            position = candidates[-1]
            # Checked after a batch, so a partial page always has a cursor.
            if self._out_of_time():
                return matched, position, True

    def _opensearch_first_request(self) -> ContentMatchRequest:
        """The text match with every filter that OpenSearch applies the same
        way as Postgres, or more loosely: Postgres checks the matches again."""
        scope = self._scope
        # Postgres counts a selected node's own document, such as a
        # Confluence page; the index lists only its descendants under it.
        attached_document_ids = scope.attached_document_ids + (
            hierarchy_node_own_document_ids(self._db_session, scope.hierarchy_node_ids)
            if scope.hierarchy_node_ids
            else []
        )
        return ContentMatchRequest(
            phrases=self._phrases,
            filters=self._access_filters.model_copy(
                update={
                    "source_type": self._filters["source_type"],
                    "document_set": scope.document_set_names or None,
                    "attached_document_ids": attached_document_ids or None,
                    "hierarchy_node_ids": scope.hierarchy_node_ids or None,
                    "updated_at_range": scope.updated_at_range,
                    "created_at_range": scope.created_at_range,
                    "tags": scope.tags,
                }
            ),
            updated_after=self._filters.get("updated_after"),
            updated_before=self._filters.get("updated_before"),
            restricted_sources=self._censoring_sources,
            restricted_source_cc_pair_ids=self._uncensored_cc_pair_ids,
        )

    def _passing(self, document_ids: list[str]) -> set[str]:
        return filter_document_ids_for_tool(
            self._db_session,
            self._user.email,
            self._external_group_ids,
            document_ids,
            **self._postgres_kwargs(),
        )

    def _match_opensearch_first(
        self, order: DocumentOrder, after: ContentMatchKey | None, limit: int
    ) -> tuple[list[DocumentCursor], DocumentCursor | None, bool]:
        date_field = date_field_for_order(order)
        if date_field is None:
            raise ValueError(f"Bug: content listings cannot order by {order}.")
        request = self._opensearch_first_request()
        kept: list[DocumentCursor] = []
        position = after
        while True:
            try:
                matches = self._document_index.match_documents_by_content(
                    request, date_field, order.is_descending, position, MATCH_BATCH_SIZE
                )
            except OpenSearchServerSideTimeout:
                # Keep the batches already checked; with none, the call fails.
                if position is None or position == after:
                    raise
                return kept, _as_cursor(position), True
            passing = (
                self._passing([match.document_id for match in matches])
                if matches
                else set()
            )
            for match in matches:
                if match.document_id not in passing:
                    continue
                kept.append(_as_cursor(match))
                if len(kept) > limit:
                    return kept[:limit], kept[limit - 1], False
            if len(matches) < MATCH_BATCH_SIZE:
                return kept, None, False
            position = matches[-1]
            if self._out_of_time():
                return kept, _as_cursor(position), True

    def _count_postgres_first(self) -> ContentMatchCount:
        count = 0
        position: DocumentCursor | None = None
        while True:
            if self._out_of_time() or count >= MAX_COUNT:
                return ContentMatchCount(count=count, is_complete=False)
            candidates = self._candidates(DocumentOrder.UPDATED_DESC, position)
            try:
                if candidates:
                    count += len(self._matching_candidates(candidates))
            except OpenSearchServerSideTimeout:
                # Keep the batches already counted; with none, the call fails.
                if position is None:
                    raise
                return ContentMatchCount(count=count, is_complete=False)
            if len(candidates) < CANDIDATE_BATCH_SIZE:
                return ContentMatchCount(count=count, is_complete=True)
            position = candidates[-1]

    def _count_opensearch_first_checked(self) -> ContentMatchCount:
        request = self._opensearch_first_request()
        count = 0
        position: ContentMatchKey | None = None
        while True:
            if self._out_of_time() or count >= MAX_COUNT:
                return ContentMatchCount(count=count, is_complete=False)
            try:
                matches = self._document_index.match_documents_by_content(
                    request,
                    ContentMatchDateField.UPDATED,
                    True,
                    position,
                    MATCH_BATCH_SIZE,
                )
            except OpenSearchServerSideTimeout:
                # Keep the batches already counted; with none, the call fails.
                if position is None:
                    raise
                return ContentMatchCount(count=count, is_complete=False)
            if matches:
                count += len(self._passing([match.document_id for match in matches]))
            if len(matches) < MATCH_BATCH_SIZE:
                return ContentMatchCount(count=count, is_complete=True)
            position = matches[-1]

    def _load_rows(
        self, keys: list[DocumentCursor], order: DocumentOrder
    ) -> list[tuple[Document, DocumentSource]]:
        """The page's documents with their sources, in the page's order."""
        if not keys:
            return []
        page = query_documents_for_tool(
            self._db_session,
            self._user.email,
            self._external_group_ids,
            order=order,
            limit=len(keys),
            document_ids=[key.document_id for key in keys],
            **self._postgres_kwargs(),
        )
        rows_by_id = {document.id: (document, source) for document, source in page.rows}
        return [
            rows_by_id[key.document_id] for key in keys if key.document_id in rows_by_id
        ]


def _as_cursor(key: ContentMatchKey) -> DocumentCursor:
    return DocumentCursor(sort_value=key.date, document_id=key.document_id)
