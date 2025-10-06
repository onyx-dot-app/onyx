from base64 import urlsafe_b64decode
from typing import Any
from typing import cast
from typing import Dict

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.google_utils import execute_single_retrieval
from onyx.connectors.google_utils.resources import get_admin_service
from onyx.connectors.google_utils.resources import get_gmail_service
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.connectors.google_utils.shared_constants import ONYX_SCOPE_INSTRUCTIONS
from onyx.connectors.google_utils.shared_constants import SLIM_BATCH_SIZE
from onyx.connectors.google_utils.shared_constants import USER_FIELDS
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import Document
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
    parts = payload.get("parts", [])
    message_body = ""
    for part in parts:
        mime_type = part.get("mimeType")
        body = part.get("body")
        if mime_type == "text/plain" and body:
            data = body.get("data", "")
            text = urlsafe_b64decode(data).decode()
            message_body += text
    return message_body


def message_to_section(message: Dict[str, Any]) -> tuple[TextSection, dict[str, str]]:
    link = f"https://mail.google.com/mail/u/0/#inbox/{message['id']}"

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


class GmailConnector(LoadConnector, PollConnector, SlimConnectorWithPermSync):
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

        except Exception:
            raise

    def _fetch_threads(
        self,
        time_range_start: SecondsSinceUnixEpoch | None = None,
        time_range_end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        query = _build_time_range_query(time_range_start, time_range_end)
        doc_batch = []
        for user_email in self._get_all_user_emails():
            gmail_service = get_gmail_service(self.creds, user_email)
            try:
                for thread in execute_paginated_retrieval(
                    retrieval_function=gmail_service.users().threads().list,
                    list_key="threads",
                    userId=user_email,
                    fields=THREAD_LIST_FIELDS,
                    q=query,
                    continue_on_404_or_403=True,
                ):
                    full_threads = execute_single_retrieval(
                        retrieval_function=gmail_service.users().threads().get,
                        list_key=None,
                        userId=user_email,
                        fields=THREAD_FIELDS,
                        id=thread["id"],
                        continue_on_404_or_403=True,
                    )
                    # full_threads is an iterator containing a single thread
                    # so we need to convert it to a list and grab the first element
                    full_thread = list(full_threads)[0]
                    doc = thread_to_document(full_thread, user_email)
                    if doc is None:
                        continue

                    doc_batch.append(doc)
                    if len(doc_batch) > self.batch_size:
                        yield doc_batch
                        doc_batch = []
            except HttpError as e:
                if _is_mail_service_disabled_error(e):
                    logger.warning(
                        "Skipping Gmail sync for %s because the mailbox is disabled.",
                        user_email,
                    )
                    continue
                raise

        if doc_batch:
            yield doc_batch

    def _fetch_slim_threads(
        self,
        time_range_start: SecondsSinceUnixEpoch | None = None,
        time_range_end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        query = _build_time_range_query(time_range_start, time_range_end)
        doc_batch = []
        for user_email in self._get_all_user_emails():
            logger.info(f"Fetching slim threads for user: {user_email}")
            gmail_service = get_gmail_service(self.creds, user_email)
            try:
                for thread in execute_paginated_retrieval(
                    retrieval_function=gmail_service.users().threads().list,
                    list_key="threads",
                    userId=user_email,
                    fields=THREAD_LIST_FIELDS,
                    q=query,
                    continue_on_404_or_403=True,
                ):
                    doc_batch.append(
                        SlimDocument(
                            id=thread["id"],
                            external_access=ExternalAccess(
                                external_user_emails={user_email},
                                external_user_group_ids=set(),
                                is_public=False,
                            ),
                        )
                    )
                    if len(doc_batch) > SLIM_BATCH_SIZE:
                        yield doc_batch
                        doc_batch = []

                        if callback:
                            if callback.should_stop():
                                raise RuntimeError(
                                    "retrieve_all_slim_docs_perm_sync: Stop signal detected"
                                )

                            callback.progress("retrieve_all_slim_docs_perm_sync", 1)
            except HttpError as e:
                if _is_mail_service_disabled_error(e):
                    logger.warning(
                        "Skipping slim Gmail sync for %s because the mailbox is disabled.",
                        user_email,
                    )
                    continue
                raise

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        try:
            yield from self._fetch_threads()
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        try:
            yield from self._fetch_threads(start, end)
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        try:
            yield from self._fetch_slim_threads(start, end, callback=callback)
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e


if __name__ == "__main__":
    pass
