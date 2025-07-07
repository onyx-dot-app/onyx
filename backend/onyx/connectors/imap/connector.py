import copy
import email
import imaplib
from email.message import Message
from email.utils import parseaddr
from typing import Any
from typing import cast

import bs4

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.imap.models import EmailHeaders
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import CredentialsConnector
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


_DEFAULT_IMAP_PORT_NUMBER = 993
_IMAP_OKAY_STATUS = "OK"
_PAGE_SIZE = 100


class ImapCheckpoint(ConnectorCheckpoint):
    todo_email_ids: list[str] = []


class ImapConnector(
    CheckpointedConnector[ImapCheckpoint],
    CredentialsConnector,
):
    def __init__(
        self,
        host: str,
        port: int = _DEFAULT_IMAP_PORT_NUMBER,
    ) -> None:
        self._host = host
        self._port = port
        self._username: str | None = None
        self._password: str | None = None
        self._mail_client = imaplib.IMAP4_SSL(host=host, port=port)

    # impls for BaseConnector
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use `set_credentials_provider` instead")

    def validate_connector_settings(self) -> None:
        raise NotImplementedError

    # impls for CredentialsConnector

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        credentials = credentials_provider.get_credentials()

        def get_or_raise(name: str) -> str:
            value = credentials.get(name)
            if not value:
                raise RuntimeError(f"Credential item {name=} was not found")
            if not isinstance(value, str):
                raise RuntimeError(
                    f"Credential item {name=} must be of type str, instead received {type(name)=}"
                )
            return value

        username = get_or_raise("username")
        password = get_or_raise("password")

        self._mail_client.login(user=username, password=password)

    # impls for CheckpointedConnector

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
    ) -> CheckpointOutput[ImapCheckpoint]:
        if not checkpoint.todo_email_ids:
            # This is the first time running this connector.
            # Populate the todo_email_ids and return a checkpoint.
            email_ids = _fetch_email_ids(mail_client=self._mail_client)
            return ImapCheckpoint(has_more=True, todo_email_ids=email_ids)

        current_todos = cast(
            list, copy.deepcopy(checkpoint.todo_email_ids[:_PAGE_SIZE])
        )
        future_todos = cast(list, copy.deepcopy(checkpoint.todo_email_ids[_PAGE_SIZE:]))

        for email_id in current_todos:
            email_msg = _fetch_email(mail_client=self._mail_client, email_id=email_id)
            if not email_msg:
                logger.warn(f"Failed to fetch message {email_id=}; skipping")
                continue

            email_headers = EmailHeaders.from_email_msg(email_msg=email_msg)

            yield _convert_email_headers_and_body_into_document(
                email_msg=email_msg, email_headers=email_headers
            )

        return ImapCheckpoint(has_more=bool(future_todos), todo_email_ids=future_todos)

    def build_dummy_checkpoint(self) -> ImapCheckpoint:
        return ImapCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ImapCheckpoint:
        raise NotImplementedError


def _fetch_email(mail_client: imaplib.IMAP4_SSL, email_id: str) -> Message | None:
    status, msg_data = mail_client.fetch(message_set=email_id, message_parts="(RFC822)")
    if status != _IMAP_OKAY_STATUS or not msg_data:
        return None

    data = msg_data[0]
    if not isinstance(data, tuple):
        raise RuntimeError(
            f"Message data should be a tuple; instead got a {type(data)=} {data=}"
        )

    _other, raw_email = data
    return email.message_from_bytes(raw_email)


def _fetch_email_ids(mail_client: imaplib.IMAP4_SSL) -> list[str]:
    status, _ids = mail_client.select("Inbox", readonly=True)
    if status != _IMAP_OKAY_STATUS:
        raise RuntimeError

    status, email_ids_byte_array = mail_client.search(None, "ALL")

    if status != _IMAP_OKAY_STATUS or not email_ids_byte_array:
        raise RuntimeError(f"Failed to fetch email ids; {status=}")

    email_ids: bytes = email_ids_byte_array[0]

    return [email_id.decode() for email_id in email_ids.split()]


def _convert_email_headers_and_body_into_document(
    email_msg: Message,
    email_headers: EmailHeaders,
) -> Document:
    _sender_name, sender_addr = parseaddr(addr=email_headers.sender)
    recipient_name, recipient_addr = parseaddr(addr=email_headers.recipient)
    title = f"{sender_addr} to {recipient_addr} about {email_headers.subject}"
    email_body = _parse_email_body(email_msg=email_msg, email_headers=email_headers)

    return Document(
        id=email_headers.id,
        title=title,
        semantic_identifier=email_headers.subject,
        metadata={},
        source=DocumentSource.IMAP,
        sections=[TextSection(text=email_body)],
        primary_owners=[
            BasicExpertInfo(
                display_name=recipient_name,
                email=recipient_addr,
            )
        ],
        external_access=ExternalAccess(
            external_user_emails=set([recipient_addr]),
            external_user_group_ids=set(),
            is_public=False,
        ),
    )


def _parse_email_body(
    email_msg: Message,
    email_headers: EmailHeaders,
) -> str:
    body = None
    for part in email_msg.walk():
        if part.is_multipart():
            continue

        charset = part.get_content_charset() or "utf-8"

        try:
            raw_payload = part.get_payload(decode=True)
            if not isinstance(raw_payload, bytes):
                logger.warn(
                    "Payload section from email was expected to be an array of bytes, instead got "
                    f"{type(raw_payload)=}, {raw_payload=}"
                )
                continue
            body = raw_payload.decode(charset)
            break
        except (UnicodeDecodeError, LookupError) as e:
            print(f"Warning: Could not decode part with charset {charset}. Error: {e}")
            continue

    if not body:
        logger.warn(
            f"Email with {email_headers.id=} has an empty body; returning an empty string"
        )
        return ""

    soup = bs4.BeautifulSoup(markup=body, features="html.parser")

    return "".join(str_section for str_section in soup.stripped_strings)


if __name__ == "__main__":
    import os
    import time

    username = os.environ.get("IMAP_USERNAME")
    password = os.environ.get("IMAP_PASSWORD")
    oauth2_token = os.environ.get("IMAP_OAUTH2_TOKEN")

    imap_connector = ImapConnector(
        host="imap.fastmail.com",
    )

    imap_connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={
                "username": username,
                "password": password,
                "oauth2_token": oauth2_token,
            },
        )
    )

    checkpoint = imap_connector.build_dummy_checkpoint()
    while True:
        for doc in imap_connector.load_from_checkpoint(
            start=0.0, end=time.time(), checkpoint=checkpoint
        ):
            print(doc)

    # for doc in load_all_docs_from_checkpoint_connector(
    #     connector=imap_connector,
    #     start=0,
    #     end=time.time(),
    # ):
    #     print(doc)
    #     ...
