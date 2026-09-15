"""Outlook connector: Microsoft 365 mail over Graph.

One document per conversation per mailbox. Every Graph call goes through
``OutlookSourceOperations``. The walk is mailbox by mailbox, folder by folder,
one delta page per checkpoint step, so a large tenant survives worker restarts.

Incremental runs come from the poll window rather than saved delta links: an
index attempt starts from a fresh checkpoint, so each folder's delta round
opens with ``receivedDateTime ge start`` and any conversation that gained a
message in the window is rebuilt whole.

Pruning walks the same mailboxes and folders but reads only conversation ids,
so a conversation whose every message was deleted leaves the index without a
full re-index. A conversation that lost one message keeps the stale text
until it gains a message or a full re-index rebuilds it.
"""

from collections import deque
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.microsoft_utils.drive_items import SizeCapExceeded
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    resolve_microsoft_environment,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.outlook.errors import (
    EXCHANGE_SCOPE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.outlook.mailboxes import (
    MAILBOX_UNAVAILABLE_STATUSES,
    describe_unavailable_mailboxes,
    raise_if_unavailable,
)
from onyx.connectors.outlook.models import (
    OutlookAttachment,
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
from onyx.file_processing.extract_file_text import (
    extract_file_text_locally,
    get_file_ext,
)
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.process_isolation import run_in_isolated_process

logger = setup_logger()

# Conversation ids per batch handed to pruning.
SLIM_BATCH_SIZE = 500

# Skipped by default. Resolved by well-known name per mailbox, because display
# names are localized and an admin's exclusion list is not.
DEFAULT_EXCLUDED_WELL_KNOWN_FOLDERS = ("junkemail", "deleteditems", "drafts", "outbox")

# A conversation longer than this keeps only its newest indexable messages.
MAX_MESSAGES_PER_CONVERSATION = 100

# Raw messages read per conversation while looking for indexable ones, so a
# thread that is mostly drafts or trashed replies stays bounded.
CONVERSATION_FETCH_LIMIT = 500

# Conversation ids a mailbox remembers this attempt so a thread is rebuilt once
# however many of its messages the delta lists. The checkpoint is written after
# every step, so past this many the oldest ids are forgotten first.
MAX_TRACKED_CONVERSATIONS_PER_MAILBOX = 20_000

# Pages of the tenant's user listing one step may read. No tenant has this many
# users, so running past it means the paging never ends.
MAX_MAILBOX_LISTING_PAGES = 10_000

# Attachment bytes come from whoever sent the mail, so what one message and
# one conversation can cost is capped however far the files expand or however
# many of them fail.
MAX_ATTACHMENTS_PER_MESSAGE = 20
MAX_ATTACHMENT_TEXT_PER_CONVERSATION = 1_000_000
MAX_ATTACHMENT_READS_PER_CONVERSATION = 25

# The deadline of the child process that parses an attachment, PDFium and the
# pypdf fallback included.
ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS = 120


# Graph stops a filtered delta round at this many messages without saying so.
# A folder that fills the cap is read again without the filter, which has no
# cap, and the poll window is applied to each entry here instead.
FILTERED_DELTA_CAP = 5000

MAILBOX_NODE_PREFIX = "outlook-mailbox:"
DOCUMENT_ID_PREFIX = "outlook:"


class OutlookCheckpoint(ConnectorCheckpoint):
    # None until enumerated, then the mailboxes still to walk, popped from the end.
    mailboxes: list[OutlookMailbox] | None = None
    current_mailbox: OutlookMailbox | None = None
    # None until the current mailbox's tree is listed, then folders left to walk.
    folders: list[OutlookFolder] | None = None
    # Every folder id under an excluded root, so a conversation message filed
    # deep inside Deleted Items is dropped like one at its top.
    excluded_folder_ids: list[str] = []
    current_folder: OutlookFolder | None = None
    delta_next_link: str | None = None
    # Entries seen in the current folder's delta round, to detect the cap.
    folder_change_count: int = 0
    # True once the current folder is being re-read without the server filter.
    folder_unfiltered: bool = False
    # Conversations already rebuilt for the current mailbox in this attempt,
    # oldest first, the newest MAX_TRACKED_CONVERSATIONS_PER_MAILBOX kept.
    seen_conversation_ids: dict[str, None] = {}


def _remember_conversation(seen: dict[str, None], conversation_id: str) -> None:
    """Records a rebuilt conversation, forgetting the oldest past the cap, so a
    busy thread stays deduplicated while the checkpoint stays bounded."""
    seen[conversation_id] = None
    if len(seen) > MAX_TRACKED_CONVERSATIONS_PER_MAILBOX:
        del seen[next(iter(seen))]


def mailbox_node_id(mailbox: OutlookMailbox) -> str:
    return f"{MAILBOX_NODE_PREFIX}{mailbox.id}"


def conversation_document_id(mailbox: OutlookMailbox, conversation_id: str) -> str:
    """Keyed by mailbox because the same conversation has a different readership
    in every mailbox it sits in."""
    return f"{DOCUMENT_ID_PREFIX}{mailbox.id}:{conversation_id}"


def _mailbox_link(mailbox: OutlookMailbox) -> str:
    return f"https://outlook.office.com/mail/{mailbox.address}/"


def _mailbox_failure(
    address: str, message: str, exception: Exception | None = None
) -> ConnectorFailure:
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=address),
        failure_message=message,
        exception=exception,
    )


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


def indexable_messages(
    messages: list[OutlookMessage], excluded_folder_ids: set[str]
) -> list[OutlookMessage]:
    """Drop drafts and messages sitting in excluded folders."""
    return [
        message
        for message in messages
        if not message.is_draft and message.parent_folder_id not in excluded_folder_ids
    ]


def attachment_skip_reason(attachment: OutlookAttachment) -> str | None:
    """Why an attachment is not worth a download, None when it is."""
    if not attachment.is_file:
        return "not a file attachment"
    if attachment.is_inline:
        return "inline attachment"
    if (
        get_file_ext(attachment.name)
        not in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS
    ):
        return "unsupported file type"
    if attachment.size > OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD:
        return "over the size threshold"
    return None


@dataclass
class AttachmentBudget:
    """What one conversation may still spend on attachments: characters kept
    and download-plus-extraction attempts, successful or not."""

    text: int = MAX_ATTACHMENT_TEXT_PER_CONVERSATION
    reads: int = MAX_ATTACHMENT_READS_PER_CONVERSATION

    @property
    def spent(self) -> bool:
        return self.text <= 0 or self.reads <= 0


def extract_attachment_text(data: bytes, name: str, cap: int) -> str:
    """Runs in a child process: the in-process parsers only, since the
    Unstructured key lives in a database the child cannot reach, PDFium in
    this process so no grandchild outlives it, and the cap applied here so the
    parent never receives more text than it keeps."""
    text = extract_file_text_locally(BytesIO(data), name, isolate_pdfium=False)
    return text.strip()[:cap]


def build_conversation_document(
    mailbox: OutlookMailbox,
    conversation_id: str,
    messages: list[OutlookMessage],
    attachment_sections: dict[str, list[TextSection]] | None = None,
) -> Document | None:
    """Assemble indexable messages of one conversation into a document, oldest
    first, each message followed by the text of its attachments. None when
    there is nothing to index."""
    kept = sorted(messages, key=_message_sort_key)[-MAX_MESSAGES_PER_CONVERSATION:]
    if not kept:
        return None

    attachments = attachment_sections or {}
    sections: list[TextSection] = []
    for message in kept:
        sections.append(_message_section(message))
        sections.extend(attachments.get(message.id, []))
    subject = next((m.subject for m in kept if m.subject), None) or "(no subject)"
    primary_owners, secondary_owners = _owners(kept)
    newest = kept[-1]
    return Document(
        id=conversation_document_id(mailbox, conversation_id),
        sections=sections,
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


class OutlookConnector(
    CredentialsConnector, CheckpointedConnector[OutlookCheckpoint], SlimConnector
):
    def __init__(
        self,
        mailboxes: list[str] | None = None,
        excluded_folders: list[str] | None = None,
        include_attachments: bool = False,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # An empty list means every mailbox the app may open.
        self.mailboxes = [a.strip() for a in mailboxes or [] if a.strip()]
        self.include_attachments = include_attachments
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
            raise ConnectorMissingCredentialError("Outlook")
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
        except OutlookGraphError as e:
            raise_for_graph_error(e, "Microsoft's token endpoint refused the request.")

        if not self.mailboxes:
            try:
                self.ops.list_mailbox_users(page_size=1)
            except OutlookGraphError as e:
                raise_for_graph_error(
                    e, "The app cannot list the tenant's users for every-mailbox mode."
                )
            return
        raise_if_unavailable(describe_unavailable_mailboxes(self.ops, self.mailboxes))

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
            yield from self._open_mailbox(checkpoint, checkpoint.mailboxes[-1])
            # Popped only once opened or skipped, so a raised Graph error
            # leaves the mailbox queued for the retry.
            checkpoint.mailboxes.pop()
            return checkpoint

        if checkpoint.current_folder is None:
            if not checkpoint.folders:
                self._finish_mailbox(checkpoint)
                return checkpoint
            checkpoint.current_folder = checkpoint.folders.pop()
            self._reset_folder_cursor(checkpoint)

        yield from self._read_folder_page(checkpoint, start, end)
        return checkpoint

    def _reset_folder_cursor(self, checkpoint: OutlookCheckpoint) -> None:
        checkpoint.delta_next_link = None
        checkpoint.folder_change_count = 0
        checkpoint.folder_unfiltered = False

    def _finish_mailbox(self, checkpoint: OutlookCheckpoint) -> None:
        checkpoint.current_mailbox = None
        checkpoint.folders = None
        checkpoint.current_folder = None
        checkpoint.excluded_folder_ids = []
        checkpoint.seen_conversation_ids = {}
        self._reset_folder_cursor(checkpoint)

    def _mailbox_unavailable(
        self, mailbox: OutlookMailbox, error: OutlookGraphError
    ) -> Generator[ConnectorFailure, None, None]:
        """A mailbox that is unlicensed or out of the app's Exchange scope is a
        recorded failure when the admin named it and a log line otherwise."""
        if self.mailboxes:
            yield _mailbox_failure(
                mailbox.address,
                f"Mailbox {mailbox.address} is unavailable ({error.code}). "
                f"{EXCHANGE_SCOPE_REMEDIATION}",
                error,
            )
            return
        logger.info(
            "Outlook: skipping %s, mailbox unavailable (%s)",
            mailbox.address,
            error.code,
        )

    def _resolve_mailboxes(
        self,
    ) -> tuple[list[OutlookMailbox], list[ConnectorFailure]]:
        """The mailboxes to walk, in configured order, plus a failure per
        configured address that matches no user."""
        found: list[OutlookMailbox] = []
        failures: list[ConnectorFailure] = []
        if self.mailboxes:
            for address in self.mailboxes:
                # Resolution reads the directory, never the mailbox, so a Graph
                # error here is about the app or the service and fails the
                # attempt instead of dropping the address.
                mailbox = self.ops.resolve_mailbox(address=address)
                if mailbox is None:
                    failures.append(
                        _mailbox_failure(
                            address,
                            f"No user matches {address}. "
                            f"{MAILBOX_UNAVAILABLE_REMEDIATION}",
                        )
                    )
                    continue
                found.append(mailbox)
        else:
            # TODO(nmgarza5): list across checkpoint steps and carry compact
            # mailbox records, so a huge tenant survives a failure mid-listing.
            next_link: str | None = None
            for _ in range(MAX_MAILBOX_LISTING_PAGES):
                page = self.ops.list_mailbox_users(next_link=next_link)
                found.extend(page.mailboxes)
                next_link = page.next_link
                if next_link is None:
                    break
            if next_link is not None:
                raise RuntimeError(
                    "Outlook: the user listing ran past "
                    f"{MAX_MAILBOX_LISTING_PAGES} pages without ending"
                )
        # A UPN and a primary SMTP address, or two listing pages, can name the
        # same mailbox. The dict keeps the first occurrence in order.
        unique = list({mailbox.id: mailbox for mailbox in found}.values())
        logger.info("Outlook: %s mailboxes to walk", len(unique))
        return unique, failures

    def _enumerate_mailboxes(
        self, checkpoint: OutlookCheckpoint
    ) -> Generator[ConnectorFailure, None, None]:
        mailboxes, failures = self._resolve_mailboxes()
        # Popped from the end, so reverse to keep the configured order.
        checkpoint.mailboxes = list(reversed(mailboxes))
        # Yielded once the checkpoint is complete, so a lookup that raises
        # part way does not repeat them on the retry.
        yield from failures

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every conversation document id the walk would produce today, so
        pruning drops the conversations that vanished.

        Reads folder and delta metadata only, never a body. A mailbox whose
        probe answers 404 is gone and contributes nothing, so its documents go
        too. Any other Graph failure raises: an aborted prune deletes nothing,
        while a silent skip would delete every document of that mailbox.
        """
        del start, end
        mailboxes, failures = self._resolve_mailboxes()
        # An address that matches no user is a configuration problem, not a
        # verdict on the mailbox behind it, so the prune stops here rather than
        # treat every conversation of that mailbox as gone.
        if failures:
            addresses = ", ".join(
                failure.failed_entity.entity_id
                for failure in failures
                if failure.failed_entity is not None
            )
            raise ConnectorValidationError(
                f"Cannot prune while these mailboxes match no user: {addresses}. "
                "Fix or remove them from the mailbox list."
            )
        for mailbox in mailboxes:
            try:
                self.ops.probe_mailbox(mailbox_id=mailbox.id)
            except OutlookGraphError as e:
                if e.status == 404:
                    logger.info("Outlook: %s is gone, pruning it", mailbox.address)
                    continue
                raise
            # A 404 past the probe is a folder that vanished mid-walk, not the
            # mailbox, so it aborts the prune like any other error.
            excluded = self._excluded_well_known_folder_ids(mailbox)
            tree = list(self._walk_folder_tree(mailbox, excluded))
            yield list(self._hierarchy_nodes(mailbox, tree))
            yield from self._slim_conversations(mailbox, tree, callback)

    def _slim_conversations(
        self,
        mailbox: OutlookMailbox,
        tree: list[tuple[OutlookFolder, str]],
        callback: IndexingHeartbeatInterface | None,
    ) -> GenerateSlimDocumentOutput:
        """Conversation ids of every folder in the tree, batched across folders
        and deduplicated per page. The parent is left unset so pruning keeps the
        folder indexing chose. Any Graph error raises, since pruning must see
        the whole mailbox or nothing."""
        batch: list[SlimDocument | HierarchyNode] = []
        for folder, _ in tree:
            next_link: str | None = None
            while True:
                # A 410 mid-round is not restarted here: ids already yielded
                # from the expired round cannot be retracted, so the prune
                # aborts and runs again later.
                page = self.ops.fetch_folder_delta_page(
                    mailbox_id=mailbox.id, folder_id=folder.id, next_link=next_link
                )
                conversation_ids = dict.fromkeys(
                    change.conversation_id
                    for change in page.changes
                    if not change.removed and change.conversation_id
                )
                batch.extend(
                    SlimDocument(id=conversation_document_id(mailbox, conversation_id))
                    for conversation_id in conversation_ids
                )
                while len(batch) >= SLIM_BATCH_SIZE:
                    yield batch[:SLIM_BATCH_SIZE]
                    batch = batch[SLIM_BATCH_SIZE:]
                if callback is not None:
                    callback.progress("outlook_slim_docs", len(conversation_ids))
                next_link = page.next_link
                if next_link is None:
                    break
        if batch:
            yield batch

    def _open_mailbox(
        self, checkpoint: OutlookCheckpoint, mailbox: OutlookMailbox
    ) -> Generator[HierarchyNode | ConnectorFailure, None, None]:
        """Probe the mailbox, then list its whole folder tree.

        Nothing is yielded until the tree is known, so a listing that fails
        part way leaves nothing behind for the retry to repeat.
        """
        try:
            self.ops.probe_mailbox(mailbox_id=mailbox.id)
            excluded = self._excluded_well_known_folder_ids(mailbox)
            tree = list(self._walk_folder_tree(mailbox, excluded))
        except OutlookGraphError as e:
            if e.status not in MAILBOX_UNAVAILABLE_STATUSES:
                raise
            yield from self._mailbox_unavailable(mailbox, e)
            return

        yield from self._hierarchy_nodes(mailbox, tree)

        checkpoint.current_mailbox = mailbox
        checkpoint.folders = list(reversed([folder for folder, _ in tree]))
        checkpoint.excluded_folder_ids = sorted(excluded)
        checkpoint.current_folder = None
        checkpoint.seen_conversation_ids = {}
        self._reset_folder_cursor(checkpoint)

    def _hierarchy_nodes(
        self, mailbox: OutlookMailbox, tree: list[tuple[OutlookFolder, str]]
    ) -> Generator[HierarchyNode, None, None]:
        yield HierarchyNode(
            raw_node_id=mailbox_node_id(mailbox),
            raw_parent_id=None,
            display_name=mailbox.display_name or mailbox.address,
            link=_mailbox_link(mailbox),
            node_type=HierarchyNodeType.MAILBOX,
        )
        for folder, parent_node_id in tree:
            yield HierarchyNode(
                raw_node_id=folder.id,
                raw_parent_id=parent_node_id,
                display_name=folder.display_name,
                node_type=HierarchyNodeType.FOLDER,
            )

    def _excluded_well_known_folder_ids(self, mailbox: OutlookMailbox) -> set[str]:
        excluded: set[str] = set()
        for name in DEFAULT_EXCLUDED_WELL_KNOWN_FOLDERS:
            folder = self.ops.get_well_known_folder(mailbox_id=mailbox.id, name=name)
            if folder is not None:
                excluded.add(folder.id)
        return excluded

    def _walk_folder_tree(
        self, mailbox: OutlookMailbox, excluded: set[str]
    ) -> Generator[tuple[OutlookFolder, str], None, None]:
        """Yield every indexable folder with its hierarchy parent id, breadth
        first. Excluded subtrees are still descended so ``excluded`` ends up
        holding every folder id a conversation message could sit in."""
        root_id = mailbox_node_id(mailbox)
        # (parent folder id or None for the root, hierarchy parent raw id, excluded)
        queue: deque[tuple[str | None, str, bool]] = deque([(None, root_id, False)])
        while queue:
            parent_folder_id, parent_node_id, parent_excluded = queue.popleft()
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
                    is_excluded = (
                        parent_excluded
                        or folder.is_hidden
                        or folder.id in excluded
                        or folder.display_name.casefold() in self.excluded_folder_names
                    )
                    if is_excluded:
                        excluded.add(folder.id)
                    else:
                        yield folder, parent_node_id
                    if folder.child_folder_count > 0:
                        queue.append((folder.id, folder.id, is_excluded))
                next_link = page.next_link
                if next_link is None:
                    break

    def _read_folder_page(
        self,
        checkpoint: OutlookCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        mailbox = checkpoint.current_mailbox
        folder = checkpoint.current_folder
        assert mailbox is not None and folder is not None

        window_start = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        try:
            page = self.ops.fetch_folder_delta_page(
                mailbox_id=mailbox.id,
                folder_id=folder.id,
                received_after=None if checkpoint.folder_unfiltered else window_start,
                next_link=checkpoint.delta_next_link,
            )
        except OutlookGraphError as e:
            # Graph drops delta state with 410. Start the folder's round over.
            if e.status == 410 and checkpoint.delta_next_link is not None:
                checkpoint.delta_next_link = None
                checkpoint.folder_change_count = 0
                return
            # The folder disappeared mid-run. Nothing left to index in it.
            if e.status == 404:
                logger.info(
                    "Outlook: folder %s in %s vanished, skipping",
                    folder.display_name,
                    mailbox.address,
                )
                checkpoint.current_folder = None
                return
            # Access to the whole mailbox is gone, so stop walking it rather
            # than record one failure per remaining folder.
            if e.status == 403:
                yield from self._mailbox_unavailable(mailbox, e)
                self._finish_mailbox(checkpoint)
                return
            raise

        end_at = datetime.fromtimestamp(end, tz=timezone.utc) if end else None
        excluded = set(checkpoint.excluded_folder_ids)
        for change in page.changes:
            if change.removed or not change.conversation_id:
                continue
            # Read-state entries arrive for old messages whatever the filter
            # says, so the window is applied again here.
            if (
                window_start
                and change.received_at
                and change.received_at < window_start
            ):
                continue
            if end_at and change.received_at and change.received_at > end_at:
                continue
            if change.conversation_id in checkpoint.seen_conversation_ids:
                continue
            result = self._rebuild_conversation(
                mailbox, change.conversation_id, excluded
            )
            _remember_conversation(
                checkpoint.seen_conversation_ids, change.conversation_id
            )
            if result is not None:
                yield result

        # Committed with the cursor, so a page replayed after a failure part
        # way through is counted once.
        checkpoint.folder_change_count += len(page.changes)
        checkpoint.delta_next_link = page.next_link
        if page.next_link is not None:
            return
        filled_cap = (
            window_start is not None
            and not checkpoint.folder_unfiltered
            and checkpoint.folder_change_count >= FILTERED_DELTA_CAP
        )
        if filled_cap:
            logger.info(
                "Outlook: folder %s in %s filled the filtered delta cap, "
                "re-reading it without the filter",
                folder.display_name,
                mailbox.address,
            )
            self._reset_folder_cursor(checkpoint)
            checkpoint.folder_unfiltered = True
            return
        checkpoint.current_folder = None

    def _rebuild_conversation(
        self,
        mailbox: OutlookMailbox,
        conversation_id: str,
        excluded_folder_ids: set[str],
    ) -> Document | ConnectorFailure | None:
        document_id = conversation_document_id(mailbox, conversation_id)
        # Pages arrive newest first, so the walk stops at the newest indexable
        # messages however many drafts or trashed replies sit among them.
        kept: list[OutlookMessage] = []
        fetched = 0
        next_link: str | None = None
        try:
            while True:
                page = self.ops.fetch_conversation_messages_page(
                    mailbox_id=mailbox.id,
                    conversation_id=conversation_id,
                    next_link=next_link,
                )
                # The budget applies to raw messages, so a final page is cut
                # to what is left of it before filtering.
                within_budget = page.messages[: CONVERSATION_FETCH_LIMIT - fetched]
                fetched += len(within_budget)
                kept.extend(indexable_messages(within_budget, excluded_folder_ids))
                next_link = page.next_link
                if (
                    next_link is None
                    or len(kept) >= MAX_MESSAGES_PER_CONVERSATION
                    or fetched >= CONVERSATION_FETCH_LIMIT
                ):
                    break
            # Cut here so attachments are read only for the messages the
            # document keeps.
            kept = kept[:MAX_MESSAGES_PER_CONVERSATION]
            attachments: dict[str, list[TextSection]] = {}
            budget = AttachmentBudget()
            for message in kept:
                if not (self.include_attachments and message.has_attachments):
                    continue
                attachments[message.id] = self._attachment_sections(
                    mailbox, message, budget
                )
        except OutlookGraphError as e:
            # A recorded failure lets the poll window move past the mail, so a
            # transient failure raises and keeps the checkpoint for the retry.
            if e.is_transient:
                raise
            return ConnectorFailure(
                failed_document=DocumentFailure(document_id=document_id),
                failure_message=(
                    f"Failed to fetch conversation {conversation_id} in "
                    f"{mailbox.address}: {e}"
                ),
                exception=e,
            )
        return build_conversation_document(mailbox, conversation_id, kept, attachments)

    def _attachment_sections(
        self, mailbox: OutlookMailbox, message: OutlookMessage, budget: AttachmentBudget
    ) -> list[TextSection]:
        """The extracted text of a message's file attachments, one section each,
        charged to the conversation's budget.

        An attachment Graph refuses is skipped with a warning. A throttled, 5xx
        or dropped call raises like a message read does, so the checkpoint is kept.
        """
        if budget.spent:
            return []
        try:
            attachments = self.ops.list_message_attachments(
                mailbox_id=mailbox.id,
                message_id=message.id,
                limit=MAX_ATTACHMENTS_PER_MESSAGE,
            )
        except OutlookGraphError as e:
            if e.is_transient:
                raise
            logger.warning(
                "Outlook: attachments of %s unreadable (%s), skipping",
                message.id,
                e.code,
            )
            return []

        sections: list[TextSection] = []
        for attachment in attachments:
            if budget.spent:
                logger.info("Outlook: attachment budget spent in %s", message.id)
                break
            text = self._attachment_text(mailbox, message, attachment, budget)
            if not text:
                continue
            budget.text -= len(text)
            sections.append(
                TextSection(
                    link=message.web_link,
                    text=f"Attachment: {attachment.name}\n\n{text}",
                )
            )
        return sections

    def _attachment_text(
        self,
        mailbox: OutlookMailbox,
        message: OutlookMessage,
        attachment: OutlookAttachment,
        budget: AttachmentBudget,
    ) -> str:
        """One attachment's text within the budget, or "" when it is skipped:
        not worth reading, over the byte cap, refused by Graph or by the
        parsers. A transient Graph error raises."""
        reason = attachment_skip_reason(attachment)
        if reason is not None:
            logger.debug("Outlook: skipping attachment %s, %s", attachment.name, reason)
            return ""
        # Charged up front so attachments that fail still count.
        budget.reads -= 1
        try:
            data = self.ops.download_attachment(
                mailbox_id=mailbox.id,
                message_id=message.id,
                attachment_id=attachment.id,
                cap=OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
            )
        except SizeCapExceeded:
            logger.info("Outlook: skipping attachment %s over the cap", attachment.name)
            return ""
        except OutlookGraphError as e:
            if e.is_transient:
                raise
            logger.warning(
                "Outlook: attachment %s unreadable (%s), skipping",
                attachment.name,
                e.code,
            )
            return ""
        # A parser refusing the file, a crash and a timeout all cost this
        # attachment only, the way break_on_unprocessable=False would.
        try:
            return run_in_isolated_process(
                extract_attachment_text,
                data,
                attachment.name,
                budget.text,
                timeout=ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "Outlook: extraction of %s failed (%s), skipping", attachment.name, e
            )
            return ""
