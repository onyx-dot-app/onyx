import copy
import time
from collections.abc import Callable, Iterator
from typing import Any, cast

from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    ConnectorFailure,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.zendesk.access import (
    access_enabled,
    get_article_access,
    get_ticket_access,
    grants_end_users,
    has_internal_note,
)
from onyx.connectors.zendesk.models import (
    ZendeskGroup,
    ZendeskOrganization,
    ZendeskTicketPage,
    ZendeskUser,
)
from onyx.connectors.zendesk.source_operations import (
    ZENDESK_SUBDOMAIN,
    ZendeskRequestError,
    ZendeskSourceOperations,
    next_cursor,
    subdomain_from_credential,
)
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

MAX_AUTHOR_MAP_SIZE = 50_000  # Reset author map cache if it gets too large
_SLIM_BATCH_SIZE = 1000


class ZendeskCredentialsNotSetUpError(PermissionError):
    def __init__(self) -> None:
        super().__init__(
            "Zendesk Credentials are not set up, was load_credentials called?"
        )


def _iterate_articles(
    ops: ZendeskSourceOperations, start_time: int | None
) -> Iterator[dict[str, Any]]:
    after_cursor: str | None = None
    while True:
        page = ops.get_article_page(start_time=start_time, after_cursor=after_cursor)
        yield from page.data
        if not page.has_more:
            return
        after_cursor = next_cursor(page.meta, after_cursor)


def _skips_article(article: dict[str, Any]) -> bool:
    """Articles indexing leaves out. The slim listings leave them out too, so
    pruning removes them."""
    return (
        article.get("body") is None
        or bool(article.get("draft"))
        or any(
            label in ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS
            for label in article.get("label_names", [])
        )
    )


def _skips_ticket(ticket: dict[str, Any]) -> bool:
    return ticket.get("status") == "deleted"


def _iterate_ticket_pages(
    ops: ZendeskSourceOperations, start_time: int | None, include_access: bool
) -> Iterator[ZendeskTicketPage]:
    next_start_time: int | None = start_time
    while True:
        page = ops.get_ticket_page(
            start_time=next_start_time, include_access=include_access
        )
        yield page
        if not page.has_more:
            return
        next_start_time = page.meta["end_time"]


def _fetch_author(
    ops: ZendeskSourceOperations, author_id: str | int
) -> BasicExpertInfo | None:
    # Skip fetching if author_id is invalid
    # cast to str to avoid issues with zendesk changing their types
    if not author_id or str(author_id) == "-1":
        return None

    user = ops.get_user(user_id=author_id)
    return (
        BasicExpertInfo(display_name=user.name, email=user.email)
        if user and user.name and user.email
        else None
    )


def _article_to_document(
    article: dict[str, Any],
    content_tags: dict[str, str],
    author_map: dict[str, BasicExpertInfo],
    ops: ZendeskSourceOperations,
) -> tuple[dict[str, BasicExpertInfo] | None, Document]:
    author_id = article.get("author_id")
    if not author_id:
        author = None
    else:
        author = (
            author_map.get(author_id)
            if author_id in author_map
            else _fetch_author(ops, author_id)
        )

    new_author_mapping = {author_id: author} if author_id and author else None

    updated_at = article.get("updated_at")
    update_time = time_str_to_utc(updated_at) if updated_at else None
    created_at = article.get("created_at")
    create_time = time_str_to_utc(created_at) if created_at else None

    # Build metadata
    metadata: dict[str, str | list[str]] = {
        "labels": [str(label) for label in article.get("label_names", []) if label],
        "content_tags": [
            content_tags[tag_id]
            for tag_id in article.get("content_tag_ids", [])
            if tag_id in content_tags
        ],
    }

    # Remove empty values
    metadata = {k: v for k, v in metadata.items() if v}

    return new_author_mapping, Document(
        id=f"article:{article['id']}",
        sections=[
            TextSection(
                link=cast(str, article.get("html_url")),
                text=parse_html_page_basic(article["body"]),
            )
        ],
        source=DocumentSource.ZENDESK,
        semantic_identifier=article["title"],
        doc_updated_at=update_time,
        doc_created_at=create_time,
        primary_owners=[author] if author else None,
        metadata=metadata,
    )


def _get_comment_text(
    comment: dict[str, Any],
    author_map: dict[str, BasicExpertInfo],
    ops: ZendeskSourceOperations,
) -> tuple[dict[str, BasicExpertInfo] | None, str]:
    author_id = comment.get("author_id")
    if not author_id:
        author = None
    else:
        author = (
            author_map.get(author_id)
            if author_id in author_map
            else _fetch_author(ops, author_id)
        )

    new_author_mapping = {author_id: author} if author_id and author else None

    comment_text = f"Comment{' by ' + author.display_name if author and author.display_name else ''}"
    comment_text += f"{' at ' + comment['created_at'] if comment.get('created_at') else ''}:\n{comment['body']}"

    return new_author_mapping, comment_text


def _ticket_to_document(
    ticket: dict[str, Any],
    author_map: dict[str, BasicExpertInfo],
    ops: ZendeskSourceOperations,
    default_subdomain: str,
    access_for: Callable[[list[dict[str, Any]]], ExternalAccess | None],
) -> tuple[dict[str, BasicExpertInfo] | None, Document]:
    """`access_for` gets the ticket's comments, which decide whether end users
    may read it."""
    submitter_id = ticket.get("submitter_id")
    if not submitter_id:
        submitter = None
    else:
        submitter = (
            author_map.get(submitter_id)
            if submitter_id in author_map
            else _fetch_author(ops, submitter_id)
        )

    new_author_mapping = (
        {submitter_id: submitter} if submitter_id and submitter else None
    )

    updated_at = ticket.get("updated_at")
    update_time = time_str_to_utc(updated_at) if updated_at else None
    created_at = ticket.get("created_at")
    create_time = time_str_to_utc(created_at) if created_at else None

    metadata: dict[str, str | list[str]] = {}
    if status := ticket.get("status"):
        metadata["status"] = status
    if priority := ticket.get("priority"):
        metadata["priority"] = priority
    if tags := ticket.get("tags"):
        metadata["tags"] = tags
    if ticket_type := ticket.get("type"):
        metadata["ticket_type"] = ticket_type

    comments = ops.list_ticket_comments(ticket_id=ticket["id"])

    comment_texts = []
    for comment in comments:
        comment_author_mapping, comment_text = _get_comment_text(
            comment, author_map, ops
        )
        if comment_author_mapping:
            author_map.update(comment_author_mapping)
        comment_texts.append(comment_text)

    comments_text = "\n\n".join(comment_texts)

    subject = ticket.get("subject")
    full_text = f"Ticket Subject:\n{subject}\n\nComments:\n{comments_text}"

    ticket_url = ticket.get("url")
    subdomain = (
        ticket_url.split("//")[1].split(".zendesk.com")[0]
        if ticket_url
        else default_subdomain
    )

    ticket_display_url = (
        f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}"
    )

    return new_author_mapping, Document(
        id=f"zendesk_ticket_{ticket['id']}",
        sections=[TextSection(link=ticket_display_url, text=full_text)],
        source=DocumentSource.ZENDESK,
        semantic_identifier=f"Ticket #{ticket['id']}: {subject or 'No Subject'}",
        doc_updated_at=update_time,
        doc_created_at=create_time,
        primary_owners=[submitter] if submitter else None,
        metadata=metadata,
        external_access=access_for(comments),
    )


_TicketSideloads = tuple[
    dict[int, ZendeskUser], dict[int, ZendeskGroup], dict[int, ZendeskOrganization]
]


def _sideload_maps(page: ZendeskTicketPage) -> _TicketSideloads:
    return (
        {user.id: user for user in page.users},
        {group.id: group for group in page.groups},
        {organization.id: organization for organization in page.organizations},
    )


class ZendeskConnectorCheckpoint(ConnectorCheckpoint):
    # We use cursor-based paginated retrieval for articles
    after_cursor_articles: str | None

    # We use timestamp-based paginated retrieval for tickets
    next_start_time_tickets: int | None

    cached_author_map: dict[str, BasicExpertInfo] | None
    cached_content_tags: dict[str, str] | None


class ZendeskConnector(
    SlimConnector,
    SlimConnectorWithPermSync,
    CheckpointedConnectorWithPermSync[ZendeskConnectorCheckpoint],
):
    slim_listing_honors_indexing_start = True

    def __init__(
        self,
        content_type: str = "articles",
        calls_per_minute: int | None = None,
        grant_end_users: bool = False,
    ) -> None:
        self.content_type = content_type
        self.grant_end_users = grant_end_users
        self.subdomain = ""
        # Fetch all tags ahead of time
        self.content_tags: dict[str, str] = {}
        self.calls_per_minute = calls_per_minute
        self._ops: ZendeskSourceOperations | None = None
        self._help_center_public: bool | None = None

    @property
    def ops(self) -> ZendeskSourceOperations:
        if self._ops is None:
            raise ZendeskCredentialsNotSetUpError()
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.subdomain = subdomain_from_credential(credentials[ZENDESK_SUBDOMAIN])
        self._ops = ZendeskSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.ZENDESK.value, credentials
            ),
            connector_specific_config={"calls_per_minute": self.calls_per_minute},
        )
        return None

    def _is_help_center_public(self, article_id: int) -> bool:
        """One anonymous read per run: whether the Help Center serves articles
        visible to everyone without sign-in."""
        if self._help_center_public is None:
            self._help_center_public = self.ops.is_article_public(article_id=article_id)
        return self._help_center_public

    def _article_access(self, article: dict[str, Any]) -> ExternalAccess | None:
        if not access_enabled():
            return None
        has_segments: bool = bool(
            article.get("user_segment_ids") or article.get("user_segment_id")
        )
        help_center_public: bool = not has_segments and self._is_help_center_public(
            article["id"]
        )
        return get_article_access(self.subdomain, article, help_center_public)

    def _ticket_access(
        self,
        ticket: dict[str, Any],
        sideloads: _TicketSideloads,
        comments: list[dict[str, Any]] | None,
    ) -> ExternalAccess | None:
        """End users are granted only with grant_end_users, and only for
        tickets without an internal note. Without comments, reads them only
        when an end user would be granted. A ticket whose comments are gone
        counts as having an internal note."""
        if not access_enabled():
            return None
        users, groups, organizations = sideloads
        internal_note: bool = True
        if self.grant_end_users and grants_end_users(ticket, users, organizations):
            if comments is None:
                try:
                    comments = self.ops.list_ticket_comments(ticket_id=ticket["id"])
                except ZendeskRequestError as e:
                    if e.status_code != 404:
                        raise
                    comments = None
            internal_note = comments is None or has_internal_note(comments)
        return get_ticket_access(
            self.subdomain, ticket, users, groups, organizations, internal_note
        )

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ZendeskConnectorCheckpoint,
    ) -> CheckpointOutput[ZendeskConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ZendeskConnectorCheckpoint,
    ) -> CheckpointOutput[ZendeskConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ZendeskConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[ZendeskConnectorCheckpoint]:
        if checkpoint.cached_content_tags is None:
            # Tickets have no content tags, and Support-only accounts have no
            # Help Center to read them from.
            checkpoint.cached_content_tags = (
                self.ops.list_content_tags() if self.content_type == "articles" else {}
            )
            return checkpoint  # save the content tags to the checkpoint
        self.content_tags = checkpoint.cached_content_tags

        if self.content_type == "articles":
            checkpoint = yield from self._retrieve_articles(
                start, end, checkpoint, include_permissions
            )
            return checkpoint
        elif self.content_type == "tickets":
            checkpoint = yield from self._retrieve_tickets(
                start, end, checkpoint, include_permissions
            )
            return checkpoint
        else:
            raise ValueError(f"Unsupported content_type: {self.content_type}")

    def _retrieve_articles(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        checkpoint: ZendeskConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[ZendeskConnectorCheckpoint]:
        checkpoint = copy.deepcopy(checkpoint)
        # This one is built on the fly as there may be more many more authors than tags
        author_map: dict[str, BasicExpertInfo] = checkpoint.cached_author_map or {}
        after_cursor = checkpoint.after_cursor_articles
        doc_batch: list[Document] = []

        response = self.ops.get_article_page(
            start_time=int(start) if start else None,
            after_cursor=after_cursor,
        )
        articles = response.data
        has_more = response.has_more
        after_cursor = response.meta.get("after_cursor")
        for article in articles:
            if _skips_article(article):
                continue

            try:
                new_author_map, document = _article_to_document(
                    article, self.content_tags, author_map, self.ops
                )
                if include_permissions:
                    document.external_access = self._article_access(article)
            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=f"article:{article.get('id')}",
                        document_link=article.get("html_url", ""),
                    ),
                    failure_message=str(e),
                    exception=e,
                )
                continue

            if new_author_map:
                author_map.update(new_author_map)

            doc_batch.append(document)

        if not has_more:
            yield from doc_batch
            checkpoint.has_more = False
            return checkpoint

        # Sometimes no documents are retrieved, but the cursor
        # is still updated so the connector makes progress.
        yield from doc_batch
        checkpoint.after_cursor_articles = after_cursor

        last_doc_updated_at = doc_batch[-1].doc_updated_at if doc_batch else None
        checkpoint.has_more = bool(
            end is None
            or last_doc_updated_at is None
            or last_doc_updated_at.timestamp() <= end
        )
        checkpoint.cached_author_map = (
            author_map if len(author_map) <= MAX_AUTHOR_MAP_SIZE else None
        )
        return checkpoint

    def _retrieve_tickets(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        checkpoint: ZendeskConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[ZendeskConnectorCheckpoint]:
        checkpoint = copy.deepcopy(checkpoint)

        author_map: dict[str, BasicExpertInfo] = checkpoint.cached_author_map or {}

        doc_batch: list[Document] = []
        next_start_time = int(checkpoint.next_start_time_tickets or start or 0)
        ticket_response = self.ops.get_ticket_page(
            start_time=next_start_time, include_access=include_permissions
        )
        sideloads: _TicketSideloads = _sideload_maps(ticket_response)
        tickets = ticket_response.data
        has_more = ticket_response.has_more
        next_start_time = ticket_response.meta["end_time"]
        for ticket in tickets:
            if _skips_ticket(ticket):
                continue

            try:
                new_author_map, document = _ticket_to_document(
                    ticket=ticket,
                    author_map=author_map,
                    ops=self.ops,
                    default_subdomain=self.subdomain,
                    access_for=lambda comments, ticket=ticket: (
                        self._ticket_access(ticket, sideloads, comments)
                        if include_permissions
                        else None
                    ),
                )
            except Exception as e:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=f"zendesk_ticket_{ticket.get('id')}",
                        document_link=ticket.get("url", ""),
                    ),
                    failure_message=str(e),
                    exception=e,
                )
                continue

            if new_author_map:
                author_map.update(new_author_map)

            doc_batch.append(document)

        if not has_more:
            yield from doc_batch
            checkpoint.has_more = False
            return checkpoint

        yield from doc_batch
        checkpoint.next_start_time_tickets = next_start_time
        last_doc_updated_at = doc_batch[-1].doc_updated_at if doc_batch else None
        checkpoint.has_more = bool(
            end is None
            or last_doc_updated_at is None
            or last_doc_updated_at.timestamp() <= end
        )
        checkpoint.cached_author_map = (
            author_map if len(author_map) <= MAX_AUTHOR_MAP_SIZE else None
        )
        return checkpoint

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every document id, for pruning. Reads no access."""
        yield from self._slim_docs(start, callback, include_permissions=False)

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every document with who may read it."""
        yield from self._slim_docs(start, callback, include_permissions=True)

    def _slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None,
        callback: IndexingHeartbeatInterface | None,
        include_permissions: bool,
    ) -> GenerateSlimDocumentOutput:
        """A partial listing reads as deletions to pruning and doc sync, so a
        stop signal raises instead of returning."""
        start_time: int | None = int(start) if start else None
        slim_doc_batch: list[SlimDocument | HierarchyNode] = []

        def stop_if_requested() -> None:
            if callback is not None and callback.should_stop():
                raise RuntimeError("Zendesk slim listing: stop signal detected")

        if self.content_type == "articles":
            for article in _iterate_articles(self.ops, start_time=start_time):
                stop_if_requested()
                if _skips_article(article):
                    continue
                created_at = article.get("created_at")
                slim_doc_batch.append(
                    SlimDocument(
                        id=f"article:{article['id']}",
                        doc_created_at=(
                            time_str_to_utc(created_at) if created_at else None
                        ),
                        external_access=(
                            self._article_access(article)
                            if include_permissions
                            else None
                        ),
                    )
                )
                if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                    yield slim_doc_batch
                    slim_doc_batch = []
        elif self.content_type == "tickets":
            for page in _iterate_ticket_pages(
                self.ops, start_time=start_time, include_access=include_permissions
            ):
                sideloads: _TicketSideloads = _sideload_maps(page)
                for ticket in page.data:
                    # Access may read each ticket's comments, so check often.
                    stop_if_requested()
                    if _skips_ticket(ticket):
                        continue
                    created_at = ticket.get("created_at")
                    slim_doc_batch.append(
                        SlimDocument(
                            id=f"zendesk_ticket_{ticket['id']}",
                            doc_created_at=(
                                time_str_to_utc(created_at) if created_at else None
                            ),
                            external_access=(
                                self._ticket_access(ticket, sideloads, comments=None)
                                if include_permissions
                                else None
                            ),
                        )
                    )
                    if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                        yield slim_doc_batch
                        slim_doc_batch = []
                    # Per ticket: with grant_end_users, each one may read its
                    # comments, and a page can take long enough to look stalled.
                    if callback is not None:
                        callback.progress("zendesk_slim_tickets", 1)
        else:
            raise ValueError(f"Unsupported content_type: {self.content_type}")
        # A stop during the last batch must not read as a complete listing.
        stop_if_requested()
        if slim_doc_batch:
            yield slim_doc_batch

    @override
    def validate_connector_settings(self) -> None:
        try:
            if self.content_type == "tickets":
                self.ops.get_ticket_page(start_time=0, per_page=1)
            else:
                self.ops.get_article_page(start_time=0, page_size=1)
        except ZendeskRequestError as e:
            if e.status_code == 404:
                raise ConnectorValidationError(
                    "Zendesk resource not found (HTTP 404)."
                ) from e
            raise ConnectorValidationError(f"Unexpected Zendesk error: {e}") from e

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> ZendeskConnectorCheckpoint:
        return ZendeskConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> ZendeskConnectorCheckpoint:
        return ZendeskConnectorCheckpoint(
            after_cursor_articles=None,
            next_start_time_tickets=None,
            cached_author_map=None,
            cached_content_tags=None,
            has_more=True,
        )


if __name__ == "__main__":
    import os

    connector = ZendeskConnector()
    connector.load_credentials(
        {
            "zendesk_subdomain": os.environ["ZENDESK_SUBDOMAIN"],
            "zendesk_email": os.environ["ZENDESK_EMAIL"],
            "zendesk_token": os.environ["ZENDESK_TOKEN"],
        }
    )

    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day
    document_batches = connector.load_from_checkpoint(
        one_day_ago,
        current,
        connector.build_dummy_checkpoint(),
    )

    print(next(document_batches))
