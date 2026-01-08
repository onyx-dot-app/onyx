from base64 import urlsafe_b64decode
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import cast
from typing import Dict

from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError  # type: ignore

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.google_utils import (
    execute_paginated_retrieval_with_max_pages,
)
from onyx.connectors.google_utils.google_utils import execute_single_retrieval
from onyx.connectors.google_utils.google_utils import PAGE_TOKEN_KEY
from onyx.connectors.google_utils.resources import get_admin_service
from onyx.connectors.google_utils.resources import get_gmail_service
from onyx.connectors.google_utils.resources import GmailService
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.connectors.google_utils.shared_constants import ONYX_SCOPE_INSTRUCTIONS
from onyx.connectors.google_utils.shared_constants import SLIM_BATCH_SIZE
from onyx.connectors.google_utils.shared_constants import USER_FIELDS
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import ConnectorFailure
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
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

EMAIL_FIELDS = [
    "cc",
    "bcc",
    "from",
    "to",
]

MAX_MESSAGE_BODY_BYTES = 10 * 1024 * 1024  # 10MB cap to keep large threads safe

PAGES_PER_CHECKPOINT = 1

add_retries = retry_builder(tries=50, max_delay=30)


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
        return email_address, display_name if display_name else None
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
    all_messages = full_thread.get("messages", [])
    if not all_messages:
        return None

    sections = []
    semantic_identifier = ""
    updated_at = None
    from_emails: dict[str, str | None] = {}
    other_emails: dict[str, str | None] = {}
    for message in all_messages:
        section, message_metadata = message_to_section(message)
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

    updated_at_datetime = None
    if updated_at:
        updated_at_datetime = time_str_to_utc(updated_at)

    id = full_thread.get("id")
    if not id:
        raise ValueError("Thread ID is required")

    primary_owners = _get_owners_from_emails(from_emails)
    secondary_owners = _get_owners_from_emails(other_emails)

    # If emails have no subject, match Gmail's default "no subject"
    # Search will break without a semantic identifier
    if not semantic_identifier:
        semantic_identifier = "(no subject)"

    # NOTE: we're choosing to unconditionally include perm sync info
    # (external_access) as it doesn't cost much space
    return Document(
        id=id,
        semantic_identifier=semantic_identifier,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.GMAIL,
        # This is used to perform permission sync
        primary_owners=primary_owners,
        secondary_owners=secondary_owners,
        doc_updated_at=updated_at_datetime,
        # Not adding emails to metadata because it's already in the sections
        metadata={},
        external_access=ExternalAccess(
            external_user_emails={email_used_to_fetch_thread},
            external_user_group_ids=set(),
            is_public=False,
        ),
    )


def _full_thread_from_id(
    thread_id: str,
    user_email: str,
    gmail_service: GmailService,
) -> Document | ConnectorFailure | None:
    try:
        thread = next(
            execute_single_retrieval(
                retrieval_function=gmail_service.users().threads().get,
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
        return thread_to_document(thread, user_email)
    except Exception as e:
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=thread_id, document_link=_build_document_link(thread_id)
            ),
            failure_message=f"Failed to retrieve thread {thread_id}",
            exception=e,
        )


def _slim_thread_from_id(
    thread_id: str,
    user_email: str,
    gmail_service: GmailService,
) -> SlimDocument:
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
    SlimConnectorWithPermSync, CheckpointedConnectorWithPermSync[GmailCheckpoint]
):
    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size

        self._creds: OAuthCredentials | ServiceAccountCredentials | None = None
        self._primary_admin_email: str | None = None

    @property
    def primary_admin_email(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, "
                "should not call this property "
                "before calling load_credentials"
            )
        return self._primary_admin_email

    @property
    def google_domain(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, "
                "should not call this property "
                "before calling load_credentials"
            )
        return self._primary_admin_email.split("@")[-1]

    @property
    def creds(self) -> OAuthCredentials | ServiceAccountCredentials:
        if self._creds is None:
            raise RuntimeError(
                "Creds missing, "
                "should not call this property "
                "before calling load_credentials"
            )
        return self._creds

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        primary_admin_email = credentials[DB_CREDENTIALS_PRIMARY_ADMIN_KEY]
        self._primary_admin_email = primary_admin_email

        self._creds, new_creds_dict = get_google_creds(
            credentials=credentials,
            source=DocumentSource.GMAIL,
        )
        return new_creds_dict

    def _get_all_user_emails(self) -> list[str]:
        """
        List all user emails if we are on a Google Workspace domain.
        If the domain is gmail.com, or if we attempt to call the Admin SDK and
        get a 404, fall back to using the single user.
        """

        try:
            admin_service = get_admin_service(self.creds, self.primary_admin_email)
            emails = []
            for user in execute_paginated_retrieval(
                retrieval_function=admin_service.users().list,
                list_key="users",
                fields=USER_FIELDS,
                domain=self.google_domain,
            ):
                if email := user.get("primaryEmail"):
                    emails.append(email)
            return emails

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(
                    "Received 404 from Admin SDK; this may indicate a personal Gmail account "
                    "with no Workspace domain. Falling back to single user."
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
        set_page_token: Callable[[str | None], None] = lambda x: None,
        is_slim: bool = False,
    ) -> Iterator[Document | ConnectorFailure] | GenerateSlimDocumentOutput:
        query = _build_time_range_query(time_range_start, time_range_end)
        slim_doc_batch: list[SlimDocument] = []
        logger.info(
            f"Fetching {'slim' if is_slim else 'full'} threads for user: {user_email}"
        )
        gmail_service = get_gmail_service(self.creds, user_email)
        try:
            for thread in execute_paginated_retrieval_with_max_pages(
                max_num_pages=PAGES_PER_CHECKPOINT,
                retrieval_function=gmail_service.users().threads().list,
                list_key="threads",
                userId=user_email,
                fields=THREAD_LIST_FIELDS,
                q=query,
                continue_on_404_or_403=True,
                **({PAGE_TOKEN_KEY: page_token} if page_token else {}),
            ):
                # if a page token is returned, set it and leave the function
                if isinstance(thread, str):
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
                        thread["id"], user_email, gmail_service
                    )
                    if result is not None:
                        yield result
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
        set_page_token: Callable[[str | None], None] = lambda x: None,
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
        set_page_token: Callable[[str | None], None] = lambda x: None,
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
            pt_dict: dict[str, str | None] = {PAGE_TOKEN_KEY: None}

            def set_page_token(page_token: str | None) -> None:
                pt_dict[PAGE_TOKEN_KEY] = page_token

            for user_email in self._get_all_user_emails():
                yield from self._fetch_slim_threads(
                    user_email,
                    pt_dict[PAGE_TOKEN_KEY],
                    set_page_token,
                    start,
                    end,
                    callback=callback,
                )
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def build_dummy_checkpoint(self) -> GmailCheckpoint:
        return GmailCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> GmailCheckpoint:
        return GmailCheckpoint.model_validate_json(checkpoint_json)


if __name__ == "__main__":
    pass
