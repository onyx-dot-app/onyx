import copy
import email
import imaplib
import os
import re
from datetime import datetime
from datetime import timezone
from email.message import Message
from email.utils import parseaddr
from enum import Enum
from typing import Any
from typing import cast

import bs4
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.imap.models import EmailHeaders
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
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


_DEFAULT_IMAP_PORT_NUMBER = int(os.environ.get("IMAP_PORT", 993))
_IMAP_OKAY_STATUS = "OK"
_PAGE_SIZE = 100
_USERNAME_KEY = "imap_username"
_PASSWORD_KEY = "imap_password"


class CurrentMailbox(BaseModel):
    mailbox: str
    todo_email_ids: list[str]


# An email has a list of mailboxes.
# Each mailbox has a list of email-ids inside of it.
#
# Usage:
# To use this checkpointer, first fetch all the mailboxes.
# Then, pop a mailbox and fetch all of its email-ids.
# Then, pop each email-id and fetch its content (and parse it, etc..).
# When you have popped all email-ids for this mailbox, pop the next mailbox and repeat the above process until you're done.
#
# For initial checkpointing, set both fields to `None`.
class ImapCheckpoint(ConnectorCheckpoint):
    todo_mailboxes: list[str] | None = None
    current_mailbox: CurrentMailbox | None = None


class LoginState(str, Enum):
    LoggedIn = "logged_in"
    LoggedOut = "logged_out"


class ImapConnector(
    CredentialsConnector,
    CheckpointedConnectorWithPermSync[ImapCheckpoint],
):
    def __init__(
        self,
        host: str,
        port: int = _DEFAULT_IMAP_PORT_NUMBER,
        mailboxes: list[str] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._mailboxes = mailboxes
        self._credentials: dict[str, Any] | None = None

    @property
    def credentials(self) -> dict[str, Any]:
        if not self._credentials:
            raise RuntimeError(
                "Credentials have not been initialized; call `set_credentials_provider` first"
            )
        return self._credentials

    def _get_mail_client(self) -> imaplib.IMAP4_SSL:
        """
        Returns a new `imaplib.IMAP4_SSL` instance.

        The `imaplib.IMAP4_SSL` object is supposed to be an "ephemeral" object; it's not something that you can login,
        logout, then log back into again. I.e., the following will fail:

        ```py
        mail_client.login(..)
        mail_client.logout();
        mail_client.login(..)
        ```

        Therefore, you need a fresh, new instance in order to operate with IMAP. This function gives one to you.

        # Notes
        This function will throw an error if the credentials have not yet been set.
        """

        def get_or_raise(name: str) -> str:
            value = self.credentials.get(name)
            if not value:
                raise RuntimeError(f"Credential item {name=} was not found")
            if not isinstance(value, str):
                raise RuntimeError(
                    f"Credential item {name=} must be of type str, instead received {type(name)=}"
                )
            return value

        username = get_or_raise(_USERNAME_KEY)
        password = get_or_raise(_PASSWORD_KEY)

        mail_client = imaplib.IMAP4_SSL(host=self._host, port=self._port)
        status, _data = mail_client.login(user=username, password=password)

        if status != _IMAP_OKAY_STATUS:
            raise RuntimeError(f"Failed to log into imap server; {status=}")

        return mail_client

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
        include_perm_sync: bool,
    ) -> CheckpointOutput[ImapCheckpoint]:
        checkpoint = cast(ImapCheckpoint, copy.deepcopy(checkpoint))
        checkpoint.has_more = True

        mail_client = self._get_mail_client()

        if checkpoint.todo_mailboxes is None:
            # This is the dummy checkpoint.
            # Fill it with mailboxes first.
            if self._mailboxes:
                checkpoint.todo_mailboxes = _sanitize_mailbox_names(self._mailboxes)
            else:
                fetched_mailboxes = _fetch_all_mailboxes_for_email_account(
                    mail_client=mail_client
                )
                if not fetched_mailboxes:
                    raise RuntimeError(
                        "Failed to find any mailboxes for this email account"
                    )
                checkpoint.todo_mailboxes = _sanitize_mailbox_names(fetched_mailboxes)

            return checkpoint

        if (
            not checkpoint.current_mailbox
            or not checkpoint.current_mailbox.todo_email_ids
        ):
            if not checkpoint.todo_mailboxes:
                checkpoint.has_more = False
                return checkpoint

            mailbox = checkpoint.todo_mailboxes.pop()
            email_ids = _fetch_email_ids_in_mailbox(
                mail_client=mail_client,
                mailbox=mailbox,
                start=start,
                end=end,
            )
            checkpoint.current_mailbox = CurrentMailbox(
                mailbox=mailbox,
                todo_email_ids=email_ids,
            )

        _select_mailbox(
            mail_client=mail_client, mailbox=checkpoint.current_mailbox.mailbox
        )
        current_todos = cast(
            list, copy.deepcopy(checkpoint.current_mailbox.todo_email_ids[:_PAGE_SIZE])
        )
        checkpoint.current_mailbox.todo_email_ids = (
            checkpoint.current_mailbox.todo_email_ids[_PAGE_SIZE:]
        )

        for email_id in current_todos:
            email_msg = _fetch_email(mail_client=mail_client, email_id=email_id)
            if not email_msg:
                logger.warn(f"Failed to fetch message {email_id=}; skipping")
                continue

            email_headers = EmailHeaders.from_email_msg(email_msg=email_msg)

            yield _convert_email_headers_and_body_into_document(
                email_msg=email_msg,
                email_headers=email_headers,
                include_perm_sync=include_perm_sync,
            )

        return checkpoint

    # impls for BaseConnector

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use `set_credentials_provider` instead")

    def validate_connector_settings(self) -> None:
        self._get_mail_client()

    # impls for CredentialsConnector

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._credentials = credentials_provider.get_credentials()

    # impls for CheckpointedConnector

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
    ) -> CheckpointOutput[ImapCheckpoint]:
        return self._load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint, include_perm_sync=False
        )

    def build_dummy_checkpoint(self) -> ImapCheckpoint:
        return ImapCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ImapCheckpoint:
        return ImapCheckpoint.model_validate_json(json_data=checkpoint_json)

    # impls for CheckpointedConnectorWithPermSync

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ImapCheckpoint,
    ) -> CheckpointOutput[ImapCheckpoint]:
        return self._load_from_checkpoint(
            start=start, end=end, checkpoint=checkpoint, include_perm_sync=True
        )


def _fetch_all_mailboxes_for_email_account(mail_client: imaplib.IMAP4_SSL) -> list[str]:
    status, mailboxes_data = mail_client.list(directory="*", pattern="*")
    if status != _IMAP_OKAY_STATUS:
        raise RuntimeError(f"Failed to fetch mailboxes; {status=}")

    mailboxes = []

    for mailboxes_raw in mailboxes_data:
        if isinstance(mailboxes_raw, bytes):
            mailboxes_str = mailboxes_raw.decode()
        elif isinstance(mailboxes_raw, str):
            mailboxes_str = mailboxes_raw
        else:
            logger.warn(
                f"Expected the mailbox data to be of type str, instead got {type(mailboxes_raw)=} {mailboxes_raw}; skipping"
            )
            continue

        # The mailbox LIST response output can be found here:
        # https://www.rfc-editor.org/rfc/rfc3501.html#section-7.2.2
        #
        # The general format is:
        # `(<name-attributes>) <hierarchy-delimiter> <mailbox-name>`
        #
        # The below regex matches on that pattern; from there, we select the 3rd match (index 2), which is the mailbox-name.
        match = re.match(r'\([^)]*\)\s+"([^"]+)"\s+"?(.+?)"?$', mailboxes_str)
        if not match:
            logger.warn(
                f"Invalid mailbox-data formatting structure: {mailboxes_str=}; skipping"
            )
            continue

        mailbox = match.group(2)
        mailboxes.append(mailbox)

    return mailboxes


def _select_mailbox(mail_client: imaplib.IMAP4_SSL, mailbox: str) -> None:
    status, _ids = mail_client.select(mailbox=mailbox, readonly=True)
    if status != _IMAP_OKAY_STATUS:
        raise RuntimeError(f"Failed to select {mailbox=}")


def _fetch_email_ids_in_mailbox(
    mail_client: imaplib.IMAP4_SSL,
    mailbox: str,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> list[str]:
    _select_mailbox(mail_client=mail_client, mailbox=mailbox)

    start_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%d-%b-%Y")
    end_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%d-%b-%Y")
    search_criteria = f'(SINCE "{start_str}" BEFORE "{end_str}")'

    status, email_ids_byte_array = mail_client.search(None, search_criteria)

    if status != _IMAP_OKAY_STATUS or not email_ids_byte_array:
        raise RuntimeError(f"Failed to fetch email ids; {status=}")

    email_ids: bytes = email_ids_byte_array[0]

    return [email_id.decode() for email_id in email_ids.split()]


def _fetch_email(mail_client: imaplib.IMAP4_SSL, email_id: str) -> Message | None:
    status, msg_data = mail_client.fetch(message_set=email_id, message_parts="(RFC822)")
    if status != _IMAP_OKAY_STATUS or not msg_data:
        return None

    data = msg_data[0]
    if not isinstance(data, tuple):
        raise RuntimeError(
            f"Message data should be a tuple; instead got a {type(data)=} {data=}"
        )

    _metadata, raw_email = data
    return email.message_from_bytes(raw_email)


def _convert_email_headers_and_body_into_document(
    email_msg: Message,
    email_headers: EmailHeaders,
    include_perm_sync: bool,
) -> Document:
    sender_name, sender_addr = _parse_singular_addr(raw_header=email_headers.sender)
    parsed_recipients = (
        _parse_addrs(raw_header=email_headers.recipients)
        if email_headers.recipients
        else []
    )

    expert_info_map = {
        recipient_addr: BasicExpertInfo(
            display_name=recipient_name, email=recipient_addr
        )
        for recipient_name, recipient_addr in parsed_recipients
    }
    if sender_addr not in expert_info_map:
        expert_info_map[sender_addr] = BasicExpertInfo(
            display_name=sender_name, email=sender_addr
        )

    email_body = _parse_email_body(email_msg=email_msg, email_headers=email_headers)
    primary_owners = list(expert_info_map.values())
    external_access = (
        ExternalAccess(
            external_user_emails=set(expert_info_map.keys()),
            external_user_group_ids=set(),
            is_public=False,
        )
        if include_perm_sync
        else None
    )

    return Document(
        id=email_headers.id,
        title=email_headers.subject,
        semantic_identifier=email_headers.subject,
        metadata={},
        source=DocumentSource.IMAP,
        sections=[TextSection(text=email_body)],
        primary_owners=primary_owners,
        external_access=external_access,
    )


def _parse_email_body(
    email_msg: Message,
    email_headers: EmailHeaders,
) -> str:
    body = None
    for part in email_msg.walk():
        if part.is_multipart():
            # Multipart parts are *containers* for other parts, not the actual content itself.
            # Therefore, we skip until we find the individual parts instead.
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

    return " ".join(str_section for str_section in soup.stripped_strings)


def _sanitize_mailbox_names(mailboxes: list[str]) -> list[str]:
    """
    Mailboxes with special characters in them must be enclosed by double-quotes, as per the IMAP protocol.
    Just to be safe, we wrap *all* mailboxes with double-quotes.
    """
    return [f'"{mailbox}"' for mailbox in mailboxes if mailbox]


def _parse_addrs(raw_header: str) -> list[tuple[str, str]]:
    addrs = raw_header.split(",")
    name_addr_pairs = [parseaddr(addr=addr) for addr in addrs if addr]
    return [(name, addr) for name, addr in name_addr_pairs if addr]


def _parse_singular_addr(raw_header: str) -> tuple[str, str]:
    addrs = _parse_addrs(raw_header=raw_header)
    if not addrs:
        raise RuntimeError(
            f"Parsing email header resulted in no addresses being found; {raw_header=}"
        )
    elif len(addrs) >= 2:
        raise RuntimeError(
            f"Expected a singular address, but instead got multiple; {raw_header=} {addrs=}"
        )

    return addrs[0]


if __name__ == "__main__":
    import time
    from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector
    from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider

    host = os.environ.get("IMAP_HOST")
    mailboxes_str = os.environ.get("IMAP_MAILBOXES")
    username = os.environ.get("IMAP_USERNAME")
    password = os.environ.get("IMAP_PASSWORD")

    mailboxes = (
        [mailbox.strip() for mailbox in mailboxes_str.split(",")]
        if mailboxes_str
        else []
    )

    if not host:
        raise RuntimeError("`IMAP_HOST` must be set")

    imap_connector = ImapConnector(
        host=host,
        mailboxes=mailboxes,
    )

    imap_connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            tenant_id=None,
            connector_name=DocumentSource.IMAP,
            credential_json={
                _USERNAME_KEY: username,
                _PASSWORD_KEY: password,
            },
        )
    )

    for doc in load_all_docs_from_checkpoint_connector(
        connector=imap_connector,
        start=0,
        end=time.time(),
    ):
        print(doc)
