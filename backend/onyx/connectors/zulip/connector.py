import os
import tempfile
import urllib.parse
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union

from zulip import Client

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.connectors.zulip.schemas import GetMessagesResponse
from onyx.connectors.zulip.schemas import Message
from onyx.connectors.zulip.utils import build_search_narrow
from onyx.connectors.zulip.utils import call_api
from onyx.connectors.zulip.utils import encode_zulip_narrow_operand
from onyx.utils.logger import setup_logger

# Potential improvements
# 1. Group documents messages into topics, make 1 document per topic per week
# 2. Add end date support once https://github.com/zulip/zulip/issues/25436 is solved

logger = setup_logger()


class ZulipConnector(LoadConnector, PollConnector):
    def __init__(
        self, realm_name: str, realm_url: str, batch_size: int = INDEX_BATCH_SIZE
    ) -> None:
        self.batch_size = batch_size
        self.realm_name = realm_name

        # Clean and normalize the URL
        realm_url = realm_url.strip().lower()

        # Remove any trailing slashes
        realm_url = realm_url.rstrip("/")

        # Ensure the URL has a scheme
        if not realm_url.startswith(("http://", "https://")):
            realm_url = f"https://{realm_url}"

        try:
            parsed = urllib.parse.urlparse(realm_url)

            # Extract the base domain without any paths or ports
            netloc = parsed.netloc.split(":")[0]  # Remove port if present

            if not netloc:
                raise ValueError(
                    f"Invalid realm URL format: {realm_url}. "
                    f"URL must include a valid domain name."
                )

            # Always use HTTPS for security
            self.base_url = f"https://{netloc}"
            self.client: Client | None = None

        except Exception as e:
            raise ValueError(
                f"Failed to parse Zulip realm URL: {realm_url}. "
                f"Please provide a URL in the format: domain.com or https://domain.com. "
                f"Error: {str(e)}"
            )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        contents = credentials["zuliprc_content"]
        # The input field converts newlines to spaces in the provided
        # zuliprc file. This reverts them back to newlines.
        contents_spaces_to_newlines = contents.replace(" ", "\n")
        # create a temporary zuliprc file
        tempdir = tempfile.tempdir
        if tempdir is None:
            raise Exception("Could not determine tempfile directory")
        config_file = os.path.join(tempdir, f"zuliprc-{self.realm_name}")
        with open(config_file, "w") as f:
            f.write(contents_spaces_to_newlines)
        self.client = Client(config_file=config_file)
        return None

    def _message_to_narrow_link(self, m: Message) -> str:
        try:
            stream_name = m.display_recipient  # assume str
            stream_operand = encode_zulip_narrow_operand(f"{m.stream_id}-{stream_name}")
            topic_operand = encode_zulip_narrow_operand(m.subject)

            narrow_link = f"{self.base_url}#narrow/stream/{stream_operand}/topic/{topic_operand}/near/{m.id}"
            return narrow_link
        except Exception as e:
            logger.error(f"Error generating Zulip message link: {e}")
            # Fallback to a basic link that at least includes the base URL
            return f"{self.base_url}#narrow/id/{m.id}"

    def _get_message_batch(self, anchor: str) -> Tuple[bool, List[Message]]:
        if self.client is None:
            raise ConnectorMissingCredentialError("Zulip")

        logger.info(f"Fetching messages starting with anchor={anchor}")
        request = build_search_narrow(
            limit=INDEX_BATCH_SIZE, anchor=anchor, apply_md=False
        )
        response = GetMessagesResponse(**call_api(self.client.get_messages, request))

        end = False
        if len(response.messages) == 0 or response.found_oldest:
            end = True

        # reverse, so that the last message is the new anchor
        # and the order is from newest to oldest
        return end, response.messages[::-1]

    def _message_to_doc(self, message: Message) -> Document:
        text = f"{message.sender_full_name}: {message.content}"

        try:
            # Convert timestamps to UTC datetime objects
            post_time = datetime.fromtimestamp(message.timestamp, tz=timezone.utc)
            edit_time = (
                datetime.fromtimestamp(message.last_edit_timestamp, tz=timezone.utc)
                if message.last_edit_timestamp is not None
                else None
            )

            # Use the most recent edit time if available, otherwise use post time
            doc_time = edit_time if edit_time is not None else post_time

        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse timestamp for message {message.id}: {e}")
            post_time = None
            edit_time = None
            doc_time = None

        metadata: Dict[str, Union[str, List[str]]] = {
            "stream_name": str(message.display_recipient),
            "topic": str(message.subject),
            "sender_name": str(message.sender_full_name),
            "sender_email": str(message.sender_email),
            "message_timestamp": str(message.timestamp),
            "message_id": str(message.id),
            "stream_id": str(message.stream_id),
            "has_reactions": str(len(message.reactions) > 0),
            "content_type": str(message.content_type or "text"),
        }

        # Always include edit timestamp in metadata when available
        if edit_time is not None:
            metadata["edit_timestamp"] = str(message.last_edit_timestamp)

        return Document(
            id=f"{message.stream_id}__{message.id}",
            sections=[
                TextSection(
                    link=self._message_to_narrow_link(message),
                    text=text,
                )
            ],
            source=DocumentSource.ZULIP,
            semantic_identifier=f"{message.display_recipient} > {message.subject}",
            metadata=metadata,
            doc_updated_at=doc_time,  # Use most recent edit time or post time
        )

    def _get_docs(
        self, anchor: str, start: SecondsSinceUnixEpoch | None = None
    ) -> Generator[Document, None, None]:
        message: Message | None = None
        while True:
            end, message_batch = self._get_message_batch(anchor)

            for message in message_batch:
                if start is not None and float(message.timestamp) < start:
                    return
                yield self._message_to_doc(message)

            if end or message is None:
                return

            # Last message is oldest, use as next anchor
            anchor = str(message.id)

    def _poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        # Since Zulip doesn't support searching by timestamp,
        # we have to always start from the newest message
        # and go backwards.
        anchor = "newest"

        docs = []
        for doc in self._get_docs(anchor=anchor, start=start):
            docs.append(doc)
            if len(docs) == self.batch_size:
                yield docs
                docs = []
        if docs:
            yield docs

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._poll_source(start=None, end=None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        return self._poll_source(start, end)
