import re
import time
from base64 import urlsafe_b64decode
from collections.abc import Callable, Generator, Iterator
from typing import Any, Dict, cast
from urllib.parse import quote

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError
from googleapiclient.http import BatchHttpRequest
from more_itertools import chunked

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.gmail.access import get_group_mail_access
from onyx.connectors.gmail.collaborative_inbox import (
    GROUPS_SETTINGS_SCOPE_MISSING_MESSAGE,
    CollaborativeInboxLookup,
    get_rfc_message_id,
)
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import (
    PAGE_TOKEN_KEY,
    execute_paginated_retrieval,
    execute_paginated_retrieval_with_max_pages,
    execute_single_retrieval,
    is_access_denied,
)
from onyx.connectors.google_utils.resources import (
    GmailService,
    GoogleService,
    get_google_service,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    MISSING_SCOPES_ERROR_STR,
    ONYX_SCOPE_INSTRUCTIONS,
    SLIM_BATCH_SIZE,
    USER_FIELDS,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    ConnectorFailure,
    GenerateSlimDocumentOutput,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    Document,
    DocumentFailure,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

# This is for the initial list call to get the thread ids
THREAD_LIST_FIELDS = "nextPageToken, threads(id)"

# These are the fields to retrieve using the ID from the initial list call
PARTS_FIELDS = "parts(body(data), mimeType)"
PAYLOAD_FIELDS = f"payload(headers, {PARTS_FIELDS})"
MESSAGES_FIELDS = f"messages(id, {PAYLOAD_FIELDS})"
THREADS_FIELDS = f"threads(id, {MESSAGES_FIELDS})"
THREAD_FIELDS = f"id, {MESSAGES_FIELDS}"
# Reindex also reads labels, to skip the threads the crawl does not list.
REINDEX_THREAD_FIELDS = f"id, messages(id, labelIds, {PAYLOAD_FIELDS})"
# threads.list leaves out Spam and Trash unless includeSpamTrash is set, and
# the crawl does not set it.
_CRAWL_EXCLUDED_LABELS = frozenset({"SPAM", "TRASH"})
# Every header that picks the group and the document id. A header missing
# here drops the document from the listing, and pruning deletes it.
_GROUP_MAIL_THREAD_FIELDS = "id, messages(id, payload(headers))"
_GROUP_MAIL_HEADERS = ["List-ID", "X-BeenThere", "Message-ID"]
# Bounds the length of one threads.list query for a member of many groups.
_GROUPS_PER_SEARCH_QUERY = 20
# The most threads Gmail returns in one threads.list page.
_MAX_THREADS_PER_PAGE = 500
# Upper bound on the group thread ids the slim listing holds for one mailbox.
# An id measures about 100 bytes in the set, so this holds it near 50 MB.
_MAX_GROUP_THREADS_PER_MAILBOX = 500_000

EMAIL_FIELDS = [
    "cc",
    "bcc",
    "from",
    "to",
]

MAX_MESSAGE_BODY_BYTES = 10 * 1024 * 1024  # 10MB cap to keep large threads safe

PAGES_PER_CHECKPOINT = 1
# The most pages the slim listing reads for one user (about 10 million
# threads at the default page size). It stops a bad page token from looping
# forever.
MAX_SLIM_PAGES_PER_USER = 100_000

add_retries = retry_builder(tries=50, max_delay=30)

# Gmail thread ids are lowercase hex strings.
_THREAD_ID_RE = re.compile(r"^[0-9a-f]+$")
# Crawl failures link to the mailbox that holds the thread. Reindex reads the
# mailbox back from this link.
_MAILBOX_LINK_RE = re.compile(r"^https://mail\.google\.com/mail/u/([^/#]+@[^/#]+)/#")
# Google advises at most 50 requests in one Gmail batch.
_MAX_GMAIL_BATCH_SIZE = 50
_GMAIL_BATCH_TRIES = 5


def _is_mail_service_disabled_error(error: HttpError) -> bool:
    """Detect if the Gmail API is telling us the mailbox is not provisioned."""

    if error.resp.status != 400:
        return False

    error_message = str(error)
    return (
        "Mail service not enabled" in error_message
        or "failedPrecondition" in error_message
    )


def _build_time_range_query(
    time_range_start: SecondsSinceUnixEpoch | None = None,
    time_range_end: SecondsSinceUnixEpoch | None = None,
) -> str | None:
    query = ""
    if time_range_start is not None and time_range_start != 0:
        query += f"after:{int(time_range_start)}"
    if time_range_end is not None and time_range_end != 0:
        query += f" before:{int(time_range_end)}"
    query = query.strip()

    if len(query) == 0:
        return None

    return query


def _clean_email_and_extract_name(email: str) -> tuple[str, str | None]:
    email = email.strip()
    if "<" in email and ">" in email:
        # Handle format: "Display Name <email@domain.com>"
        display_name = email[: email.find("<")].strip()
        email_address = email[email.find("<") + 1 : email.find(">")].strip()
        return email_address, display_name or None
    else:
        # Handle plain email address
        return email.strip(), None


def _get_owners_from_emails(emails: dict[str, str | None]) -> list[BasicExpertInfo]:
    owners = []
    for email, names in emails.items():
        if names:
            name_parts = names.split(" ")
            first_name = " ".join(name_parts[:-1])
            last_name = name_parts[-1]
        else:
            first_name = None
            last_name = None
        owners.append(
            BasicExpertInfo(email=email, first_name=first_name, last_name=last_name)
        )
    return owners


def _get_message_body(payload: dict[str, Any]) -> str:
    """
    Gmail threads can contain large inline parts (including attachments
    transmitted as base64). Only decode text/plain parts and skip anything
    that breaches the safety threshold to protect against OOMs.
    """

    message_body_chunks: list[str] = []
    stack = [payload]

    while stack:
        part = stack.pop()
        if not part:
            continue

        children = part.get("parts", [])
        stack.extend(reversed(children))

        mime_type = part.get("mimeType")
        if mime_type != "text/plain":
            continue

        body = part.get("body", {})
        data = body.get("data", "")

        if not data:
            continue

        # base64 inflates storage by ~4/3; work with decoded size estimate
        approx_decoded_size = (len(data) * 3) // 4
        if approx_decoded_size > MAX_MESSAGE_BODY_BYTES:
            logger.warning(
                "Skipping oversized Gmail message part (%s bytes > %s limit)",
                approx_decoded_size,
                MAX_MESSAGE_BODY_BYTES,
            )
            continue

        try:
            text = urlsafe_b64decode(data).decode()
        except (ValueError, UnicodeDecodeError) as error:
            logger.warning("Failed to decode Gmail message part: %s", error)
            continue

        message_body_chunks.append(text)

    return "".join(message_body_chunks)


def _build_document_link(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"


def _build_mailbox_document_link(thread_id: str, user_email: str) -> str:
    """Link that opens the thread in the mailbox it was read from."""
    return f"https://mail.google.com/mail/u/{user_email}/#all/{thread_id}"


def _build_group_mail_link(rfc_message_id: str) -> str:
    """Gmail message ids differ per mailbox, so the link searches Gmail for the
    Message-ID header."""
    return (
        "https://mail.google.com/mail/u/0/#search/"
        f"{quote(f'rfc822msgid:{rfc_message_id}', safe='')}"
    )


def _build_group_mail_document_id(group_email: str, rfc_message_id: str) -> str:
    """The same id from every member's copy. It names the group because a
    message sent to two groups is one document per group."""
    return f"{group_email}:{rfc_message_id}"


def _mailbox_from_document_link(document_link: str | None) -> str | None:
    if not document_link:
        return None
    match = _MAILBOX_LINK_RE.match(document_link)
    return match.group(1).lower() if match else None


def _build_thread_failure(
    thread_id: str,
    user_email: str,
    failure_message: str,
    exception: Exception | None = None,
) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(
            document_id=thread_id,
            document_link=_build_mailbox_document_link(thread_id, user_email),
        ),
        failure_message=failure_message,
        exception=exception,
    )


def message_to_section(message: Dict[str, Any]) -> tuple[TextSection, dict[str, str]]:
    link = _build_document_link(message["id"])

    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    metadata: dict[str, Any] = {}
    for header in headers:
        name = header.get("name").lower()
        value = header.get("value")
        if name in EMAIL_FIELDS:
            metadata[name] = value
        if name == "subject":
            metadata["subject"] = value
        if name == "date":
            metadata["updated_at"] = value

    if labels := message.get("labelIds"):
        metadata["labels"] = labels

    message_data = ""
    for name, value in metadata.items():
        # updated at isnt super useful for the llm
        if name != "updated_at":
            message_data += f"{name}: {value}\n"

    message_body_text: str = _get_message_body(payload)

    return TextSection(link=link, text=message_body_text + message_data), metadata


def thread_to_document(
    full_thread: Dict[str, Any], email_used_to_fetch_thread: str
) -> Document | None:
    return _messages_to_document(
        document_id=full_thread.get("id"),
        all_messages=full_thread.get("messages", []),
        external_access=ExternalAccess(
            external_user_emails={email_used_to_fetch_thread},
            external_user_group_ids=set(),
            is_public=False,
        ),
    )


def thread_to_documents(
    full_thread: dict[str, Any],
    user_email: str,
    inbox_lookup: CollaborativeInboxLookup,
) -> list[Document]:
    """One document per Collaborative Inbox message, which the group reads, and
    one for the other messages of the thread, which the mailbox owner reads."""
    group_documents: list[Document] = []
    personal_messages: list[dict[str, Any]] = []
    for message in full_thread.get("messages", []):
        group_mail_ids = _get_group_mail_ids(message, user_email, inbox_lookup)
        if group_mail_ids is None:
            personal_messages.append(message)
            continue
        group_email, rfc_message_id = group_mail_ids
        group_document = _messages_to_document(
            document_id=_build_group_mail_document_id(group_email, rfc_message_id),
            all_messages=[message],
            external_access=get_group_mail_access(group_email),
            section_link=_build_group_mail_link(rfc_message_id),
        )
        if group_document is not None:
            group_documents.append(group_document)

    personal_document = thread_to_document(
        {**full_thread, "messages": personal_messages}, user_email
    )
    if personal_document is None:
        return group_documents
    return [*group_documents, personal_document]


def _get_group_mail_ids(
    message: dict[str, Any],
    user_email: str,
    inbox_lookup: CollaborativeInboxLookup,
) -> tuple[str, str] | None:
    """The group and the Message-ID that name the group document of this copy.
    None when the copy is not Collaborative Inbox mail, or has no Message-ID."""
    group_email = inbox_lookup.get_group(message, user_email)
    if group_email is None:
        return None
    rfc_message_id = get_rfc_message_id(message)
    if rfc_message_id is None:
        return None
    return group_email, rfc_message_id


def _messages_to_document(
    document_id: str | None,
    all_messages: list[dict[str, Any]],
    external_access: ExternalAccess | None,
    section_link: str | None = None,
) -> Document | None:
    """`section_link` replaces each message's own link, which holds a Gmail
    message id that only one mailbox has."""
    if not all_messages:
        return None

    sections = []
    semantic_identifier = ""
    created_at = None
    updated_at = None
    from_emails: dict[str, str | None] = {}
    other_emails: dict[str, str | None] = {}
    for message in all_messages:
        section, message_metadata = message_to_section(message)
        if section_link is not None:
            section = TextSection(link=section_link, text=section.text)
        sections.append(section)

        for name, value in message_metadata.items():
            if name in EMAIL_FIELDS:
                email, display_name = _clean_email_and_extract_name(value)
                if name == "from":
                    from_emails[email] = (
                        display_name if not from_emails.get(email) else None
                    )
                else:
                    other_emails[email] = (
                        display_name if not other_emails.get(email) else None
                    )

        # If we haven't set the semantic identifier yet, set it to the subject of the first message
        if not semantic_identifier:
            semantic_identifier = message_metadata.get("subject", "")

        if message_metadata.get("updated_at"):
            updated_at = message_metadata.get("updated_at")
            # Messages arrive oldest-first, so the first Date header is the
            # thread's creation time.
            if not created_at:
                created_at = message_metadata.get("updated_at")

    created_at_datetime = None
    if created_at:
        try:
            created_at_datetime = time_str_to_utc(created_at)
        except (ValueError, OverflowError) as e:
            logger.warning(
                "Skipping unparseable Gmail Date header on thread %s: %r (%s)",
                document_id,
                created_at,
                e,
            )

    updated_at_datetime = None
    if updated_at:
        try:
            updated_at_datetime = time_str_to_utc(updated_at)
        except (ValueError, OverflowError) as e:
            # Old mailboxes contain RFC-violating Date headers. Drop the
            # timestamp instead of aborting the indexing run.
            logger.warning(
                "Skipping unparseable Gmail Date header on thread %s: %r (%s)",
                document_id,
                updated_at,
                e,
            )

    if not document_id:
        raise ValueError("Thread ID is required")

    primary_owners = _get_owners_from_emails(from_emails)
    secondary_owners = _get_owners_from_emails(other_emails)

    # If emails have no subject, match Gmail's default "no subject"
    # Search will break without a semantic identifier
    if not semantic_identifier:
        semantic_identifier = "(no subject)"

    return Document(
        id=document_id,
        semantic_identifier=semantic_identifier,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.GMAIL,
        # This is used to perform permission sync
        primary_owners=primary_owners,
        secondary_owners=secondary_owners,
        doc_created_at=created_at_datetime,
        doc_updated_at=updated_at_datetime,
        # Not adding emails to metadata because it's already in the sections
        metadata={},
        external_access=external_access,
    )


def _full_thread_from_id(
    thread_id: str,
    user_email: str,
    gmail_service: GmailService,
    inbox_lookup: CollaborativeInboxLookup,
) -> list[Document] | ConnectorFailure:
    try:
        thread = next(
            execute_single_retrieval(
                retrieval_function=gmail_service.users()  # ty: ignore[unresolved-attribute]
                .threads()
                .get,
                list_key=None,
                userId=user_email,
                fields=THREAD_FIELDS,
                id=thread_id,
                continue_on_404_or_403=True,
            ),
            None,
        )
        if thread is None:
            raise ValueError(f"Thread {thread_id} not found")
        return thread_to_documents(thread, user_email, inbox_lookup)
    except Exception as e:
        return _build_thread_failure(
            thread_id, user_email, f"Failed to retrieve thread {thread_id}", e
        )


def _pop_labels_and_check_crawl_listing(thread: dict[str, Any]) -> bool:
    """Remove the labels a reindex fetch adds, so the document matches the
    crawl's. Returns False if the crawl's threads.list leaves the thread out:
    every message is in Spam or Trash."""
    listed = False
    for message in thread.get("messages", []):
        labels = set(message.pop("labelIds", None) or [])
        if not labels & _CRAWL_EXCLUDED_LABELS:
            listed = True
    return listed


def _is_retryable_batch_error(error: HttpError) -> bool:
    status = error.resp.status
    return (
        status == 429
        or status >= 500
        or (status == 403 and not is_access_denied(error))
    )


def _batch_get_threads(
    gmail_service: GmailService,
    user_email: str,
    thread_ids: list[str],
    fields: str,
    metadata_headers: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Exception]]:
    """threads.get for many threads of one mailbox, in batch requests. With
    `metadata_headers`, Gmail returns only those headers and no message body.

    Returns (threads found, per-thread errors). A thread that is not in this
    mailbox is in neither dict. Rate limits and server errors are retried; if
    they persist, they become per-thread errors, never "not found".
    """
    found: dict[str, dict[str, Any]] = {}
    errors: dict[str, Exception] = {}
    retry: list[str] = []
    get_kwargs: dict[str, Any] = {"userId": user_email, "fields": fields}
    if metadata_headers is not None:
        get_kwargs["format"] = "metadata"
        get_kwargs["metadataHeaders"] = metadata_headers

    def callback(
        request_id: str,
        response: dict[str, Any],
        exception: Exception | None,
    ) -> None:
        if exception is None:
            found[request_id] = response
        elif not isinstance(exception, HttpError):
            errors[request_id] = exception
        elif is_access_denied(exception) or _is_mail_service_disabled_error(exception):
            # Not in this mailbox.
            return
        elif _is_retryable_batch_error(exception):
            retry.append(request_id)
        else:
            errors[request_id] = exception

    pending = list(thread_ids)
    for attempt in range(1, _GMAIL_BATCH_TRIES + 1):
        retry.clear()
        for start in range(0, len(pending), _MAX_GMAIL_BATCH_SIZE):
            batch = cast(
                BatchHttpRequest,
                gmail_service.new_batch_http_request(  # ty: ignore[unresolved-attribute]
                    callback=callback
                ),
            )
            chunk = pending[start : start + _MAX_GMAIL_BATCH_SIZE]
            for thread_id in chunk:
                batch.add(
                    gmail_service.users()  # ty: ignore[unresolved-attribute]
                    .threads()
                    .get(id=thread_id, **get_kwargs),
                    request_id=thread_id,
                )
            try:
                batch.execute()
            except HttpError as e:
                # The whole batch request failed, so no callback ran.
                if not _is_retryable_batch_error(e):
                    raise
                retry.extend(chunk)

        if not retry:
            break
        if attempt == _GMAIL_BATCH_TRIES:
            for thread_id in retry:
                errors[thread_id] = RuntimeError(
                    f"Gmail kept rate limiting or failing threads.get for {thread_id}"
                )
            break
        logger.info(
            "Retrying %s rate-limited Gmail thread reads for %s",
            len(retry),
            user_email,
        )
        time.sleep(2**attempt)
        pending = list(retry)
    return found, errors


def _slim_thread_from_id(
    thread_id: str,
    user_email: str,
    gmail_service: GmailService,  # noqa: ARG001
) -> SlimDocument:
    # doc_created_at is left None: the Gmail thread list returns only IDs, and
    # fetching the Date header would cost an extra API call per thread. Going-
    # forward creation time is set on the full indexing path (thread_to_document).
    return SlimDocument(
        id=thread_id,
        external_access=ExternalAccess(
            external_user_emails={user_email},
            external_user_group_ids=set(),
            is_public=False,
        ),
    )


class GmailCheckpoint(ConnectorCheckpoint):
    user_emails: list[str] = []  # stack of user emails to process
    page_token: str | None = None


class GmailConnector(
    SlimConnectorWithPermSync,
    CheckpointedConnectorWithPermSync[GmailCheckpoint],
    Resolver,
):
    slim_listing_honors_indexing_start = True

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        collaborative_inbox_groups: list[str] | None = None,
    ) -> None:
        self.batch_size = batch_size
        self.collaborative_inbox_groups = collaborative_inbox_groups or []

        self._creds: OAuthCredentials | ServiceAccountCredentials | None = None
        self._primary_admin_email: str | None = None
        self._inbox_lookup: CollaborativeInboxLookup | None = None

    @property
    def primary_admin_email(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, should not call this property before calling load_credentials"
            )
        return self._primary_admin_email

    @property
    def google_domain(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, should not call this property before calling load_credentials"
            )
        return self._primary_admin_email.split("@")[-1]

    @property
    def creds(self) -> OAuthCredentials | ServiceAccountCredentials:
        if self._creds is None:
            raise RuntimeError(
                "Creds missing, should not call this property before calling load_credentials"
            )
        return self._creds

    @property
    def inbox_lookup(self) -> CollaborativeInboxLookup:
        if self._inbox_lookup is None:
            self._inbox_lookup = CollaborativeInboxLookup(
                self.creds, self.primary_admin_email, self.collaborative_inbox_groups
            )
        return self._inbox_lookup

    def validate_connector_settings(self) -> None:
        if not self.collaborative_inbox_groups:
            return
        if not self.inbox_lookup.has_settings_access():
            raise InsufficientPermissionsError(GROUPS_SETTINGS_SCOPE_MISSING_MESSAGE)
        unusable_groups = self.inbox_lookup.get_groups_without_collaborative_inbox()
        if unusable_groups:
            raise ConnectorValidationError(
                "These addresses are not Google Groups with Collaborative Inbox "
                f"turned on: {', '.join(unusable_groups)}"
            )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        primary_admin_email = credentials[DB_CREDENTIALS_PRIMARY_ADMIN_KEY]
        self._primary_admin_email = primary_admin_email
        self._inbox_lookup = None

        self._creds, new_creds_dict = get_google_creds(
            credentials=credentials,
            source=DocumentSource.GMAIL,
        )
        return new_creds_dict

    def _get_all_user_emails(self) -> list[str]:
        """
        List all user emails if we are on a Google Workspace domain.
        If the domain is gmail.com, or if we attempt to call the Admin SDK and
        get a 404 or 403, fall back to using the single user.
        A 404 indicates a personal Gmail account with no Workspace domain.
        A 403 indicates insufficient permissions (e.g., OAuth user without admin privileges).
        """

        try:
            admin_service = get_google_service(
                GoogleService.ADMIN, self.creds, self.primary_admin_email
            )
            emails = [
                email
                for user in execute_paginated_retrieval(
                    retrieval_function=admin_service.users().list,  # ty: ignore[unresolved-attribute]
                    list_key="users",
                    fields=USER_FIELDS,
                    domain=self.google_domain,
                )
                if (email := user.get("primaryEmail"))
            ]
            return emails

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(
                    "Received 404 from Admin SDK; this may indicate a personal Gmail account "
                    "with no Workspace domain. Falling back to single user."
                )
                return [self.primary_admin_email]
            elif e.resp.status == 403:
                logger.warning(
                    "Received 403 from Admin SDK; this may indicate insufficient permissions "
                    "(e.g., OAuth user without admin privileges or service account without "
                    "domain-wide delegation). Falling back to single user."
                )
                return [self.primary_admin_email]
            raise

    def _fetch_threads_impl(
        self,
        user_email: str,
        time_range_start: SecondsSinceUnixEpoch | None = None,
        time_range_end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        page_token: str | None = None,
        set_page_token: Callable[[str | None], None] = lambda x: None,  # noqa: ARG005
        is_slim: bool = False,
    ) -> Iterator[Document | ConnectorFailure] | GenerateSlimDocumentOutput:
        query = _build_time_range_query(time_range_start, time_range_end)
        slim_doc_batch: list[SlimDocument | HierarchyNode] = []
        logger.info(
            "Fetching %s threads for user: %s",
            "slim" if is_slim else "full",
            user_email,
        )
        gmail_service = get_google_service(GoogleService.GMAIL, self.creds, user_email)
        try:
            for thread in execute_paginated_retrieval_with_max_pages(
                max_num_pages=PAGES_PER_CHECKPOINT,
                retrieval_function=gmail_service.users()  # ty: ignore[unresolved-attribute]
                .threads()
                .list,
                list_key="threads",
                userId=user_email,
                fields=THREAD_LIST_FIELDS,
                q=query,
                continue_on_404_or_403=True,
                **({PAGE_TOKEN_KEY: page_token} if page_token else {}),
            ):
                # if a page token is returned, set it and leave the function
                if isinstance(thread, str):
                    # The threads of this page must not be lost.
                    if slim_doc_batch:
                        yield slim_doc_batch
                    set_page_token(thread)
                    return
                if is_slim:
                    slim_doc_batch.append(
                        SlimDocument(
                            id=thread["id"],
                            external_access=ExternalAccess(
                                external_user_emails={user_email},
                                external_user_group_ids=set(),
                                is_public=False,
                            ),
                        )
                    )
                    if len(slim_doc_batch) >= SLIM_BATCH_SIZE:
                        yield slim_doc_batch
                        slim_doc_batch = []
                else:
                    result = _full_thread_from_id(
                        thread["id"], user_email, gmail_service, self.inbox_lookup
                    )
                    if isinstance(result, ConnectorFailure):
                        yield result
                    else:
                        yield from result
                if callback:
                    tag = (
                        "retrieve_all_slim_docs_perm_sync"
                        if is_slim
                        else "gmail_retrieve_all_docs"
                    )
                    if callback.should_stop():
                        raise RuntimeError(f"{tag}: Stop signal detected")

                    callback.progress(tag, 1)
            if slim_doc_batch:
                yield slim_doc_batch

            # done with user
            set_page_token(None)
        except HttpError as e:
            if _is_mail_service_disabled_error(e):
                logger.warning(
                    "Skipping Gmail sync for %s because the mailbox is disabled.",
                    user_email,
                )
                return
            raise

    def _fetch_threads(
        self,
        user_email: str,
        page_token: str | None = None,
        set_page_token: Callable[[str | None], None] = lambda x: None,  # noqa: ARG005
        time_range_start: SecondsSinceUnixEpoch | None = None,
        time_range_end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> Iterator[Document | ConnectorFailure]:
        yield from cast(
            Iterator[Document | ConnectorFailure],
            self._fetch_threads_impl(
                user_email,
                time_range_start,
                time_range_end,
                callback,
                page_token,
                set_page_token,
                False,
            ),
        )

    def _fetch_slim_threads(
        self,
        user_email: str,
        page_token: str | None = None,
        set_page_token: Callable[[str | None], None] = lambda x: None,  # noqa: ARG005
        time_range_start: SecondsSinceUnixEpoch | None = None,
        time_range_end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from cast(
            GenerateSlimDocumentOutput,
            self._fetch_threads_impl(
                user_email,
                time_range_start,
                time_range_end,
                callback,
                page_token,
                set_page_token,
                True,
            ),
        )

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GmailCheckpoint,
    ) -> CheckpointOutput[GmailCheckpoint]:
        if not checkpoint.user_emails:
            checkpoint.user_emails = self._get_all_user_emails()
        try:

            def set_page_token(page_token: str | None) -> None:
                checkpoint.page_token = page_token

            yield from self._fetch_threads(
                checkpoint.user_emails[-1],
                checkpoint.page_token,
                set_page_token,
                start,
                end,
                callback=None,
            )
            if checkpoint.page_token is None:
                # we're done with this user
                checkpoint.user_emails.pop()

            if len(checkpoint.user_emails) == 0:
                checkpoint.has_more = False
            return checkpoint
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GmailCheckpoint,
    ) -> CheckpointOutput[GmailCheckpoint]:
        return self._load_from_checkpoint(
            start=start,
            end=end,
            checkpoint=checkpoint,
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GmailCheckpoint,
    ) -> CheckpointOutput[GmailCheckpoint]:
        # NOTE: we're choosing to unconditionally include perm sync info
        # (external_access) as it doesn't cost much space
        return self._load_from_checkpoint(
            start=start,
            end=end,
            checkpoint=checkpoint,
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        try:
            # Pruning deletes what this listing leaves out, and nothing
            # validates the connector before it. A group that stopped
            # qualifying must fail the listing, not empty it.
            self.validate_connector_settings()

            pt_dict: dict[str, str | None] = {PAGE_TOKEN_KEY: None}

            def set_page_token(page_token: str | None) -> None:
                pt_dict[PAGE_TOKEN_KEY] = page_token

            for user_email in self._get_all_user_emails():
                group_thread_ids = self._list_group_thread_ids(user_email)
                listed_group_thread_ids: list[str] = []
                # Each call reads one page. List every page of this user,
                # and start the next user from its first page. A listing
                # that stops early would make pruning delete the threads
                # it did not list, so a stuck token raises.
                page_token: str | None = None
                for _ in range(MAX_SLIM_PAGES_PER_USER):
                    pt_dict[PAGE_TOKEN_KEY] = None
                    for slim_doc_batch in self._fetch_slim_threads(
                        user_email,
                        page_token,
                        set_page_token,
                        start,
                        end,
                        callback=callback,
                    ):
                        if group_thread_ids is None:
                            # A mailbox that lists its threads can be read, so
                            # the denied search hides group documents.
                            raise RuntimeError(
                                f"Gmail denied the group mail search of {user_email} "
                                "but listed its threads"
                            )
                        listed_group_thread_ids.extend(
                            slim_doc.id
                            for slim_doc in slim_doc_batch
                            if isinstance(slim_doc, SlimDocument)
                            and slim_doc.id in group_thread_ids
                        )
                        yield slim_doc_batch
                    if len(listed_group_thread_ids) >= SLIM_BATCH_SIZE:
                        yield from self._fetch_slim_group_mail(
                            user_email, listed_group_thread_ids, callback
                        )
                        listed_group_thread_ids = []
                    next_page_token = pt_dict[PAGE_TOKEN_KEY]
                    if next_page_token is None:
                        break
                    if next_page_token == page_token:
                        raise RuntimeError(
                            f"Gmail returned the same page token twice for {user_email}"
                        )
                    page_token = next_page_token
                else:
                    raise RuntimeError(
                        f"Gmail slim listing for {user_email} read "
                        f"{MAX_SLIM_PAGES_PER_USER} pages without reaching the end"
                    )
                yield from self._fetch_slim_group_mail(
                    user_email, listed_group_thread_ids, callback
                )
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def _list_group_thread_ids(self, user_email: str) -> set[str] | None:
        """The threads of this mailbox that hold mail from a Collaborative
        Inbox group the mailbox belongs to. None when Gmail denies the search,
        as it does for a mailbox the connector cannot read."""
        group_emails = self.inbox_lookup.get_groups_of_member(user_email)
        if not group_emails:
            return set()

        gmail_service = get_google_service(GoogleService.GMAIL, self.creds, user_email)
        thread_ids: set[str] = set()
        try:
            for group_email_batch in chunked(group_emails, _GROUPS_PER_SEARCH_QUERY):
                # No date range and Spam and Trash included: Gmail applies both
                # to each message, and the crawl indexes every message of a
                # thread that has one message in range.
                for thread in execute_paginated_retrieval(
                    retrieval_function=gmail_service.users()  # ty: ignore[unresolved-attribute]
                    .threads()
                    .list,
                    list_key="threads",
                    userId=user_email,
                    fields=THREAD_LIST_FIELDS,
                    # Gmail's `list:` takes the group address and matches the
                    # dotted List-ID.
                    q=" OR ".join(f"list:{email}" for email in group_email_batch),
                    includeSpamTrash=True,
                    maxResults=_MAX_THREADS_PER_PAGE,
                ):
                    thread_ids.add(thread["id"])
                    if len(thread_ids) > _MAX_GROUP_THREADS_PER_MAILBOX:
                        raise RuntimeError(
                            f"{user_email} holds more than "
                            f"{_MAX_GROUP_THREADS_PER_MAILBOX} group mail threads"
                        )
        except HttpError as e:
            if is_access_denied(e) or _is_mail_service_disabled_error(e):
                return None
            raise
        return thread_ids

    def _fetch_slim_group_mail(
        self,
        user_email: str,
        thread_ids: list[str],
        callback: IndexingHeartbeatInterface | None,
    ) -> GenerateSlimDocumentOutput:
        """The Collaborative Inbox documents in these threads of the mailbox."""
        if not thread_ids:
            return

        gmail_service = get_google_service(GoogleService.GMAIL, self.creds, user_email)
        for thread_id_batch in chunked(thread_ids, SLIM_BATCH_SIZE):
            threads, errors = _batch_get_threads(
                gmail_service,
                user_email,
                thread_id_batch,
                fields=_GROUP_MAIL_THREAD_FIELDS,
                metadata_headers=_GROUP_MAIL_HEADERS,
            )
            # Pruning deletes the documents a listing leaves out.
            if errors:
                raise RuntimeError(
                    f"Gmail failed to read {len(errors)} threads of "
                    f"{user_email} while listing group mail"
                )
            slim_doc_batch: list[SlimDocument | HierarchyNode] = []
            for thread in threads.values():
                for message in thread.get("messages", []):
                    group_mail_ids = _get_group_mail_ids(
                        message, user_email, self.inbox_lookup
                    )
                    if group_mail_ids is None:
                        continue
                    group_email, rfc_message_id = group_mail_ids
                    slim_doc_batch.append(
                        SlimDocument(
                            id=_build_group_mail_document_id(
                                group_email, rfc_message_id
                            ),
                            external_access=get_group_mail_access(group_email),
                        )
                    )
            if slim_doc_batch:
                yield slim_doc_batch
            if callback:
                tag = "retrieve_all_slim_docs_perm_sync"
                if callback.should_stop():
                    raise RuntimeError(f"{tag}: Stop signal detected")
                callback.progress(tag, len(thread_id_batch))

    def _reindex_from_mailbox(
        self,
        user_email: str,
        pending: dict[str, None],
    ) -> Iterator[Document | ConnectorFailure]:
        """Fetch the pending threads that are in this mailbox. Removes each
        thread that resolves (to a document or a failure) from ``pending``."""
        gmail_service = get_google_service(GoogleService.GMAIL, self.creds, user_email)
        try:
            found, errors = _batch_get_threads(
                gmail_service, user_email, list(pending), REINDEX_THREAD_FIELDS
            )
        except RefreshError as e:
            # The admin's mailbox failing means the credential is bad. Any
            # other user may be suspended or deleted; the thread can still be
            # in a later mailbox.
            if user_email == self.primary_admin_email:
                raise
            logger.warning(
                "Skipping mailbox %s during Gmail reindex: %s", user_email, e
            )
            return

        for thread_id, thread in found.items():
            pending.pop(thread_id, None)
            if not _pop_labels_and_check_crawl_listing(thread):
                yield _build_thread_failure(
                    thread_id,
                    user_email,
                    f"Thread {thread_id} is in Spam or Trash; the crawl does "
                    "not index it",
                )
                continue
            try:
                docs = thread_to_documents(thread, user_email, self.inbox_lookup)
            except Exception as e:
                yield _build_thread_failure(
                    thread_id,
                    user_email,
                    f"Failed to convert thread {thread_id} during reindex",
                    e,
                )
                continue
            if not docs:
                yield _build_thread_failure(
                    thread_id,
                    user_email,
                    f"Thread {thread_id} has no messages; nothing to reindex",
                )
                continue
            yield from docs

        for thread_id, error in errors.items():
            pending.pop(thread_id, None)
            yield _build_thread_failure(
                thread_id,
                user_email,
                f"Failed to retrieve thread {thread_id} during reindex: {error}",
                error,
            )

    def _split_group_mail_document_id(self, document_id: str) -> tuple[str, str] | None:
        """The group and the Message-ID in the id of a group document. None
        when the id does not name a group of this connector."""
        group_email, _, rfc_message_id = document_id.partition(":")
        listed_groups = {email.lower() for email in self.collaborative_inbox_groups}
        if group_email not in listed_groups or not rfc_message_id:
            return None
        return group_email, rfc_message_id

    def _reindex_group_mail(
        self,
        document_id: str,
        group_email: str,
        rfc_message_id: str,
        user_emails: list[str],
    ) -> Document | ConnectorFailure:
        """The group document, built from the first member mailbox that holds
        a copy of the message."""
        for user_email in user_emails:
            if group_email not in self.inbox_lookup.get_groups_of_member(user_email):
                continue
            gmail_service = get_google_service(
                GoogleService.GMAIL, self.creds, user_email
            )
            try:
                thread_ids = [
                    thread["id"]
                    for thread in execute_paginated_retrieval(
                        retrieval_function=gmail_service.users()  # ty: ignore[unresolved-attribute]
                        .threads()
                        .list,
                        list_key="threads",
                        userId=user_email,
                        fields=THREAD_LIST_FIELDS,
                        q=f"rfc822msgid:{rfc_message_id}",
                        continue_on_404_or_403=True,
                    )
                ]
                threads, _ = _batch_get_threads(
                    gmail_service, user_email, thread_ids, REINDEX_THREAD_FIELDS
                )
            except (HttpError, RefreshError) as e:
                # Another member may hold a copy that can be read.
                logger.warning(
                    "Skipping mailbox %s while reindexing %s: %s",
                    user_email,
                    document_id,
                    e,
                )
                continue
            for thread in threads.values():
                if not _pop_labels_and_check_crawl_listing(thread):
                    continue
                for doc in thread_to_documents(thread, user_email, self.inbox_lookup):
                    if doc.id == document_id:
                        return doc

        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=document_id,
                document_link=_build_group_mail_link(rfc_message_id),
            ),
            failure_message=(
                f"No mailbox of {group_email} that the connector reads holds "
                f"the group message {rfc_message_id}"
            ),
        )

    def _reindex(
        self, errors: list[ConnectorFailure]
    ) -> Iterator[Document | ConnectorFailure]:
        # Thread ids are per mailbox, and the id alone does not name the
        # mailbox. Crawl failures carry it in their document link. Other ids
        # are looked up in every mailbox, the admin's first.
        pending: dict[str, None] = {}
        pending_group_mail: dict[str, tuple[str, str]] = {}
        hinted_ids_by_mailbox: dict[str, list[str]] = {}
        for failure in errors:
            if failure.failed_document is None:
                continue
            thread_id = failure.failed_document.document_id
            if thread_id in pending or thread_id in pending_group_mail:
                continue
            if not _THREAD_ID_RE.match(thread_id):
                group_mail_ids = self._split_group_mail_document_id(thread_id)
                if group_mail_ids is not None:
                    pending_group_mail[thread_id] = group_mail_ids
                    continue
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=thread_id,
                        document_link=failure.failed_document.document_link,
                    ),
                    failure_message=(
                        f"'{thread_id}' is neither a Gmail thread id nor the id "
                        "of a group document of this connector"
                    ),
                )
                continue
            pending[thread_id] = None
            mailbox = _mailbox_from_document_link(failure.failed_document.document_link)
            if mailbox is not None:
                hinted_ids_by_mailbox.setdefault(mailbox, []).append(thread_id)

        if not pending and not pending_group_mail:
            return

        user_emails = self._get_all_user_emails()
        for document_id, (group_email, rfc_message_id) in pending_group_mail.items():
            yield self._reindex_group_mail(
                document_id, group_email, rfc_message_id, user_emails
            )
        # Only the mailboxes the crawl reads are in scope.
        mailbox_by_lower_email = {email.lower(): email for email in user_emails}
        for hinted_mailbox, hinted_ids in hinted_ids_by_mailbox.items():
            user_email = mailbox_by_lower_email.get(hinted_mailbox)
            if user_email is None:
                continue
            hinted_pending = {tid: None for tid in hinted_ids if tid in pending}
            yield from self._reindex_from_mailbox(user_email, hinted_pending)
            for thread_id in hinted_ids:
                if thread_id not in hinted_pending:
                    pending.pop(thread_id, None)

        # The admin's mailbox first, but only if the crawl reads it.
        search_order = sorted(
            user_emails, key=lambda email: email != self.primary_admin_email
        )
        for user_email in search_order:
            if not pending:
                break
            yield from self._reindex_from_mailbox(user_email, pending)

        for thread_id in pending:
            yield ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=thread_id,
                    document_link=_build_document_link(thread_id),
                ),
                failure_message=(
                    f"Gmail thread {thread_id} is not in any mailbox the "
                    "connector reads (deleted, or the user is gone)"
                ),
            )

    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,  # noqa: ARG002
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        # Like the crawl, the documents carry their external_access either
        # way, so include_permissions changes nothing.
        logger.info("Reindexing %s Gmail threads from errors", len(errors))
        try:
            yield from self._reindex(errors)
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise

    def build_dummy_checkpoint(self) -> GmailCheckpoint:
        return GmailCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> GmailCheckpoint:
        return GmailCheckpoint.model_validate_json(checkpoint_json)


if __name__ == "__main__":
    pass
