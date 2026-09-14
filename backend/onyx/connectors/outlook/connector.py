"""Outlook connector: Microsoft 365 mail over Graph.

One document per conversation per mailbox. Every Graph call goes through
``OutlookSourceOperations``. The walk is mailbox by mailbox, folder by folder,
one delta page per checkpoint step, so a large tenant survives worker restarts.

Incremental runs come from the poll window rather than saved delta links: an
index attempt starts from a fresh checkpoint, so each folder's delta round
opens with ``receivedDateTime ge start`` and any conversation that gained a
message in the window is rebuilt whole.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    resolve_microsoft_environment,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    TextSection,
)
from onyx.connectors.outlook.errors import (
    EXCHANGE_SCOPE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.outlook.models import (
    OutlookAuthError,
    OutlookFolder,
    OutlookGraphError,
    OutlookMailbox,
    OutlookMessage,
    OutlookRecipient,
)
from onyx.connectors.outlook.source_operations import (
    CONFIG_AUTHORITY_HOST,
    CONFIG_GRAPH_API_HOST,
    OutlookSourceOperations,
)
from onyx.db.enums import HierarchyNodeType
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Skipped by default. Resolved by well-known name per mailbox, because display
# names are localized and an admin's exclusion list is not.
DEFAULT_EXCLUDED_WELL_KNOWN_FOLDERS = ("junkemail", "deleteditems", "drafts", "outbox")

# A conversation longer than this keeps only its newest messages.
MAX_MESSAGES_PER_CONVERSATION = 100
# Upper bound on what is fetched before the cap applies, so a runaway thread
# cannot page forever.
CONVERSATION_FETCH_LIMIT = 500

# Validation probes at most this many configured mailboxes, so a long list
# still validates in time. Indexing walks every one of them.
MAX_VALIDATED_MAILBOXES = 25

MAILBOX_NODE_PREFIX = "outlook-mailbox:"
DOCUMENT_ID_PREFIX = "outlook:"

# Only statuses that describe the mailbox itself. Anything else is a real
# failure of the run.
MAILBOX_UNAVAILABLE_STATUSES = frozenset({403, 404})


class OutlookCheckpoint(ConnectorCheckpoint):
    # None until enumerated, then the mailboxes still to walk, popped from the end.
    mailboxes: list[OutlookMailbox] | None = None
    current_mailbox: OutlookMailbox | None = None
    # None until the current mailbox's tree is listed, then folders left to walk.
    folders: list[OutlookFolder] | None = None
    excluded_folder_ids: list[str] = []
    current_folder: OutlookFolder | None = None
    delta_next_link: str | None = None
    # Conversations already rebuilt for the current mailbox in this attempt.
    seen_conversation_ids: set[str] = set()


def mailbox_node_id(mailbox: OutlookMailbox) -> str:
    return f"{MAILBOX_NODE_PREFIX}{mailbox.id}"


def conversation_document_id(mailbox: OutlookMailbox, conversation_id: str) -> str:
    """Keyed by mailbox because the same conversation has a different readership
    in every mailbox it sits in."""
    return f"{DOCUMENT_ID_PREFIX}{mailbox.id}:{conversation_id}"


def _mailbox_link(mailbox: OutlookMailbox) -> str:
    return f"https://outlook.office.com/mail/{mailbox.address}/"


def _format_recipient(recipient: OutlookRecipient) -> str:
    if recipient.name and recipient.name != recipient.address:
        return f"{recipient.name} <{recipient.address}>"
    return recipient.address


def _message_sort_key(message: OutlookMessage) -> datetime:
    return (
        message.received_at
        or message.sent_at
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _message_section(message: OutlookMessage) -> TextSection:
    lines: list[str] = []
    if message.sender is not None:
        lines.append(f"From: {_format_recipient(message.sender)}")
    if message.to_recipients:
        lines.append(
            "To: " + ", ".join(_format_recipient(r) for r in message.to_recipients)
        )
    if message.cc_recipients:
        lines.append(
            "Cc: " + ", ".join(_format_recipient(r) for r in message.cc_recipients)
        )
    sent_at = message.sent_at or message.received_at
    if sent_at is not None:
        lines.append(f"Date: {sent_at.isoformat()}")
    if message.subject:
        lines.append(f"Subject: {message.subject}")
    header = "\n".join(lines)
    text = f"{header}\n\n{message.body_text}" if header else message.body_text
    return TextSection(link=message.web_link, text=text.strip())


def _expert(recipient: OutlookRecipient) -> BasicExpertInfo:
    return BasicExpertInfo(display_name=recipient.name, email=recipient.address)


def _owners(
    messages: list[OutlookMessage],
) -> tuple[list[BasicExpertInfo], list[BasicExpertInfo]]:
    """Senders are primary owners, everyone else on the thread is secondary."""
    senders: dict[str, OutlookRecipient] = {}
    others: dict[str, OutlookRecipient] = {}
    for message in messages:
        if message.sender is not None:
            senders.setdefault(message.sender.address.lower(), message.sender)
        for recipient in message.to_recipients + message.cc_recipients:
            others.setdefault(recipient.address.lower(), recipient)
    for address in senders:
        others.pop(address, None)
    return (
        [_expert(r) for r in senders.values()],
        [_expert(r) for r in others.values()],
    )


def build_conversation_document(
    mailbox: OutlookMailbox,
    conversation_id: str,
    messages: list[OutlookMessage],
    excluded_folder_ids: set[str],
) -> Document | None:
    """Assemble one conversation into a document, oldest message first.

    Drafts and messages sitting in excluded folders are dropped. None when
    nothing indexable is left.
    """
    kept = sorted(
        (
            message
            for message in messages
            if not message.is_draft
            and message.parent_folder_id not in excluded_folder_ids
        ),
        key=_message_sort_key,
    )
    if not kept:
        return None
    kept = kept[-MAX_MESSAGES_PER_CONVERSATION:]

    subject = next((m.subject for m in kept if m.subject), None) or "(no subject)"
    primary_owners, secondary_owners = _owners(kept)
    newest = kept[-1]
    return Document(
        id=conversation_document_id(mailbox, conversation_id),
        sections=[_message_section(message) for message in kept],
        source=DocumentSource.OUTLOOK,
        semantic_identifier=subject,
        title=subject,
        doc_created_at=_message_sort_key(kept[0]),
        doc_updated_at=_message_sort_key(newest),
        primary_owners=primary_owners,
        secondary_owners=secondary_owners,
        metadata={"mailbox": mailbox.address, "message_count": str(len(kept))},
        parent_hierarchy_raw_node_id=newest.parent_folder_id
        or mailbox_node_id(mailbox),
    )


class OutlookConnector(CredentialsConnector, CheckpointedConnector[OutlookCheckpoint]):
    def __init__(
        self,
        mailboxes: list[str] | None = None,
        excluded_folders: list[str] | None = None,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # An empty list means every mailbox the app may open.
        self.mailboxes = [a.strip() for a in mailboxes or [] if a.strip()]
        self.excluded_folder_names = {
            name.strip().casefold() for name in excluded_folders or [] if name.strip()
        }
        self.authority_host = authority_host.rstrip("/")
        self.graph_api_host = graph_api_host.rstrip("/")
        resolve_microsoft_environment(self.graph_api_host, self.authority_host)
        self.batch_size = batch_size
        self._ops: OutlookSourceOperations | None = None

    @property
    def ops(self) -> OutlookSourceOperations:
        if self._ops is None:
            raise RuntimeError(
                "Credentials missing, call load_credentials or set_credentials_provider first"
            )
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.OUTLOOK.value, credentials
            )
        )
        return None

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = OutlookSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={
                CONFIG_AUTHORITY_HOST: self.authority_host,
                CONFIG_GRAPH_API_HOST: self.graph_api_host,
            },
        )

    def validate_connector_settings(self) -> None:
        try:
            self.ops.check_token()
        except OutlookAuthError as e:
            raise_for_auth_error(e)

        if not self.mailboxes:
            try:
                self.ops.list_mailbox_users(page_size=1)
            except OutlookGraphError as e:
                raise_for_graph_error(
                    e, "The app cannot list the tenant's users for every-mailbox mode."
                )
            return

        unavailable: list[str] = []
        for address in self.mailboxes[:MAX_VALIDATED_MAILBOXES]:
            try:
                mailbox = self.ops.resolve_mailbox(address=address)
                if mailbox is None:
                    unavailable.append(f"{address} (no such user)")
                    continue
                self.ops.probe_mailbox(mailbox_id=mailbox.id)
            except OutlookGraphError as e:
                if e.status in MAILBOX_UNAVAILABLE_STATUSES:
                    unavailable.append(f"{address} ({e.code})")
                    continue
                raise_for_graph_error(e, f"The app cannot read `{address}`.")
        if unavailable:
            raise ConnectorValidationError(
                "These mailboxes cannot be indexed: "
                + ", ".join(unavailable)
                + f". {MAILBOX_UNAVAILABLE_REMEDIATION} {EXCHANGE_SCOPE_REMEDIATION}"
            )

    def build_dummy_checkpoint(self) -> OutlookCheckpoint:
        return OutlookCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> OutlookCheckpoint:
        return OutlookCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: OutlookCheckpoint,
    ) -> CheckpointOutput[OutlookCheckpoint]:
        """One unit of work per call: enumerate, open a mailbox, or read one
        delta page. The checkpoint records where to resume."""
        if checkpoint.mailboxes is None:
            yield from self._enumerate_mailboxes(checkpoint)
            return checkpoint

        if checkpoint.current_mailbox is None:
            if not checkpoint.mailboxes:
                checkpoint.has_more = False
                return checkpoint
            yield from self._open_mailbox(checkpoint, checkpoint.mailboxes.pop())
            return checkpoint

        if checkpoint.current_folder is None:
            if not checkpoint.folders:
                checkpoint.current_mailbox = None
                checkpoint.folders = None
                return checkpoint
            checkpoint.current_folder = checkpoint.folders.pop()
            checkpoint.delta_next_link = None

        yield from self._read_folder_page(checkpoint, start, end)
        return checkpoint

    def _enumerate_mailboxes(
        self, checkpoint: OutlookCheckpoint
    ) -> Generator[ConnectorFailure, None, None]:
        found: list[OutlookMailbox] = []
        if self.mailboxes:
            for address in self.mailboxes:
                try:
                    mailbox = self.ops.resolve_mailbox(address=address)
                except OutlookGraphError as e:
                    yield _mailbox_failure(address, f"Failed to look up {address}", e)
                    continue
                if mailbox is None:
                    yield _mailbox_failure(
                        address,
                        f"No user matches {address}. {MAILBOX_UNAVAILABLE_REMEDIATION}",
                    )
                    continue
                found.append(mailbox)
        else:
            next_link: str | None = None
            while True:
                page = self.ops.list_mailbox_users(next_link=next_link)
                found.extend(page.mailboxes)
                next_link = page.next_link
                if next_link is None:
                    break
        logger.info("Outlook: %s mailboxes to walk", len(found))
        # Popped from the end, so reverse to keep the configured order.
        checkpoint.mailboxes = list(reversed(found))

    def _open_mailbox(
        self, checkpoint: OutlookCheckpoint, mailbox: OutlookMailbox
    ) -> Generator[HierarchyNode | ConnectorFailure, None, None]:
        """Probe the mailbox, then list its whole folder tree.

        A mailbox that is unlicensed or out of the app's Exchange scope is a
        recorded failure when the admin named it and a log line otherwise.
        """
        try:
            self.ops.probe_mailbox(mailbox_id=mailbox.id)
        except OutlookGraphError as e:
            if e.status not in MAILBOX_UNAVAILABLE_STATUSES:
                raise
            if self.mailboxes:
                yield _mailbox_failure(
                    mailbox.address,
                    f"Mailbox {mailbox.address} is unavailable ({e.code}). "
                    f"{EXCHANGE_SCOPE_REMEDIATION}",
                    e,
                )
            else:
                logger.info(
                    "Outlook: skipping %s, mailbox unavailable (%s)",
                    mailbox.address,
                    e.code,
                )
            return

        root_id = mailbox_node_id(mailbox)
        yield HierarchyNode(
            raw_node_id=root_id,
            raw_parent_id=None,
            display_name=mailbox.display_name or mailbox.address,
            link=_mailbox_link(mailbox),
            node_type=HierarchyNodeType.MAILBOX,
        )

        excluded: set[str] = set()
        for name in DEFAULT_EXCLUDED_WELL_KNOWN_FOLDERS:
            folder = self.ops.get_well_known_folder(mailbox_id=mailbox.id, name=name)
            if folder is not None:
                excluded.add(folder.id)

        folders: list[OutlookFolder] = []
        # (parent folder id or None for the root, hierarchy parent raw id)
        queue: list[tuple[str | None, str]] = [(None, root_id)]
        while queue:
            parent_folder_id, parent_node_id = queue.pop(0)
            next_link: str | None = None
            while True:
                page = self.ops.list_child_folders(
                    mailbox_id=mailbox.id,
                    parent_folder_id=parent_folder_id,
                    next_link=next_link,
                )
                for folder in page.folders:
                    if folder.is_search_folder:
                        continue
                    if (
                        folder.id in excluded
                        or folder.display_name.casefold() in self.excluded_folder_names
                    ):
                        excluded.add(folder.id)
                        continue
                    yield HierarchyNode(
                        raw_node_id=folder.id,
                        raw_parent_id=parent_node_id,
                        display_name=folder.display_name,
                        node_type=HierarchyNodeType.FOLDER,
                    )
                    folders.append(folder)
                    if folder.child_folder_count > 0:
                        queue.append((folder.id, folder.id))
                next_link = page.next_link
                if next_link is None:
                    break

        checkpoint.current_mailbox = mailbox
        checkpoint.folders = list(reversed(folders))
        checkpoint.excluded_folder_ids = sorted(excluded)
        checkpoint.current_folder = None
        checkpoint.delta_next_link = None
        checkpoint.seen_conversation_ids = set()

    def _read_folder_page(
        self,
        checkpoint: OutlookCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        mailbox = checkpoint.current_mailbox
        folder = checkpoint.current_folder
        assert mailbox is not None and folder is not None

        received_after = (
            datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        )
        try:
            page = self.ops.fetch_folder_delta_page(
                mailbox_id=mailbox.id,
                folder_id=folder.id,
                received_after=received_after,
                next_link=checkpoint.delta_next_link,
            )
        except OutlookGraphError as e:
            # Graph drops delta state with 410. Start the folder's round over.
            if e.status == 410 and checkpoint.delta_next_link is not None:
                checkpoint.delta_next_link = None
                return
            if e.status not in MAILBOX_UNAVAILABLE_STATUSES:
                raise
            yield ConnectorFailure(
                failed_entity=EntityFailure(entity_id=folder.id),
                failure_message=(
                    f"Folder {folder.display_name} in {mailbox.address} became "
                    f"unreadable ({e.code})"
                ),
                exception=e,
            )
            checkpoint.current_folder = None
            return

        end_at = datetime.fromtimestamp(end, tz=timezone.utc) if end else None
        excluded = set(checkpoint.excluded_folder_ids)
        for change in page.changes:
            if change.removed or not change.conversation_id:
                continue
            if end_at and change.received_at and change.received_at > end_at:
                continue
            if change.conversation_id in checkpoint.seen_conversation_ids:
                continue
            checkpoint.seen_conversation_ids.add(change.conversation_id)
            result = self._rebuild_conversation(
                mailbox, change.conversation_id, excluded
            )
            if result is not None:
                yield result

        checkpoint.delta_next_link = page.next_link
        if page.next_link is None:
            checkpoint.current_folder = None

    def _rebuild_conversation(
        self,
        mailbox: OutlookMailbox,
        conversation_id: str,
        excluded_folder_ids: set[str],
    ) -> Document | ConnectorFailure | None:
        document_id = conversation_document_id(mailbox, conversation_id)
        try:
            messages = self.ops.list_conversation_messages(
                mailbox_id=mailbox.id,
                conversation_id=conversation_id,
                limit=CONVERSATION_FETCH_LIMIT,
            )
        except OutlookGraphError as e:
            return ConnectorFailure(
                failed_document=DocumentFailure(document_id=document_id),
                failure_message=(
                    f"Failed to fetch conversation {conversation_id} in "
                    f"{mailbox.address}: {e}"
                ),
                exception=e,
            )
        return build_conversation_document(
            mailbox, conversation_id, messages, excluded_folder_ids
        )


def _mailbox_failure(
    address: str, message: str, exception: Exception | None = None
) -> ConnectorFailure:
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=address),
        failure_message=message,
        exception=exception,
    )
