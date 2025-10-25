from __future__ import annotations

import copy
import time
from collections.abc import Iterator
from typing import Any
from typing import TYPE_CHECKING

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import SlimDocument
from onyx.connectors.pylon.models import GetIssueMessagesResponseBody
from onyx.connectors.pylon.models import GetIssuesResponseBody
from onyx.connectors.pylon.models import Issue
from onyx.connectors.pylon.models import Message
from onyx.connectors.pylon.utils import _create_id
from onyx.connectors.pylon.utils import AttachmentData
from onyx.connectors.pylon.utils import build_auth_client
from onyx.connectors.pylon.utils import build_generic_client
from onyx.connectors.pylon.utils import download_attachment
from onyx.connectors.pylon.utils import get_time_window_days
from onyx.connectors.pylon.utils import is_valid_issue
from onyx.connectors.pylon.utils import is_valid_message
from onyx.connectors.pylon.utils import map_to_document
from onyx.connectors.pylon.utils import normalize_attachment_url
from onyx.connectors.pylon.utils import parse_pylon_datetime
from onyx.connectors.pylon.utils import parse_ymd_date
from onyx.connectors.pylon.utils import pylon_get
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    import httpx

logger = setup_logger()


class PylonConnectorCheckpoint(ConnectorCheckpoint):
    """Checkpoint state for resumable Pylon indexing.

    Fields:
        current_day_start: RFC3339 day start for current sub-window

    Note: GET /issues API does not support cursor pagination per OpenAPI spec.
    Each day window returns all issues in a single response.
    """

    current_day_start: str | None = None


class PylonConnector(
    CheckpointedConnector[PylonConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    """Connector for indexing Pylon customer support data.

    Creates one document per issue. Messages and attachments are embedded
    as sections within the issue document.

    Args:
        pylon_entities: Optional entity types to include. Options: "messages", "attachments"
                 - Issues are always included (required as root entity)
                 - "messages": Include issue messages as additional sections
                 - "attachments": Process and include attachment content
        start_date: Start date for indexing in YYYY-MM-DD format
        lookback_days: Number of days to look back for updated issues (default: 7).
        The connector will fetch issues created N days before the sync window to capture
                      updates to existing issues. Issues are only re-indexed if their
                      latest_message_time falls within the sync window.
        batch_size: Number of documents per batch for indexing
    """

    def __init__(
        self,
        pylon_entities: list[str],
        start_date: str,
        lookback_days: int = 7,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # Issues are always included; entities only controls optional messages/attachments
        self.pylon_entities = pylon_entities
        self.start_epoch_sec = parse_ymd_date(start_date)
        self.lookback_days = lookback_days
        self.batch_size = batch_size
        self.base_url: str = "https://api.usepylon.com"
        self.api_key: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load Pylon API credentials.

        Expects credentials dict with:
        - pylon_api_key (required): Pylon API key
        """
        self.api_key = credentials.get("pylon_api_key")
        if not self.api_key:
            raise ConnectorMissingCredentialError("Pylon")
        return None

    def _client(self) -> httpx.Client:
        """Build authenticated HTTP client."""
        if not self.api_key:
            raise ConnectorMissingCredentialError("Pylon")
        return build_auth_client(self.api_key, self.base_url)

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: PylonConnectorCheckpoint,
    ) -> CheckpointOutput[PylonConnectorCheckpoint]:
        """Resumable indexing of Pylon issues with embedded messages and attachments.

        Each issue becomes one document with all related content embedded as sections.
        Checkpointing happens at day boundaries.

        If messages are tracked, the start time is adjusted backwards by lookback_days
        to capture updates to existing issues. Issues are filtered by latest_message_time
        to only index those with recent activity.
        """
        new_checkpoint = copy.deepcopy(checkpoint)

        messages_enabled = "messages" in self.pylon_entities
        attachments_enabled = "attachments" in self.pylon_entities

        adjusted_start = start - (self.lookback_days * 24 * 60 * 60)
        logger.info(
            f"Applying {self.lookback_days} - "
            f"(original_start={start}, adjusted_start={adjusted_start})"
        )

        start_boundary = self.start_epoch_sec
        if new_checkpoint.current_day_start:
            start_boundary = parse_pylon_datetime(new_checkpoint.current_day_start)
        time_windows = get_time_window_days(adjusted_start, end, start_boundary)
        if not time_windows:
            new_checkpoint.has_more = False
            return new_checkpoint

        for idx, (start_time, end_time) in enumerate(time_windows):
            for issue in self._iter_issues(
                start_time,
                end_time,
                messages_enabled=messages_enabled,
                original_start=start,
            ):
                if not is_valid_issue(issue):
                    logger.warning(f"Skipping invalid issue ID: {issue.id}")
                    continue
                attachments_urls = issue.attachment_urls or []
                messages = []
                if not issue.id:
                    logger.warning("Skipping issue without ID")
                    continue
                if messages_enabled:
                    for message in self._iter_messages(issue.id):
                        if not is_valid_message(message):
                            logger.warning(
                                f"Skipping invalid message ID: {message.id} for issue ID: {issue.id}"
                            )
                            continue
                        if message.file_urls:
                            attachments_urls.extend(message.file_urls)
                        messages.append(message)
                unique_attachments_data = []
                if attachments_urls and attachments_enabled:
                    unique_attachments_urls = []
                    unique_normalized_urls = set()
                    for url in attachments_urls:
                        normalized_url = normalize_attachment_url(url)
                        if (
                            normalized_url
                            and normalized_url not in unique_normalized_urls
                        ):
                            unique_normalized_urls.add(normalized_url)
                            unique_attachments_urls.append(url)
                    for attachment in self._iter_attachments(unique_attachments_urls):
                        attachment.url = normalize_attachment_url(attachment.url)
                        unique_attachments_data.append(attachment)
                try:
                    document = map_to_document(
                        issue,
                        messages,
                        unique_attachments_data,
                    )
                    yield document
                except Exception as e:
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=(_create_id(issue)),
                            document_link=issue.link,
                        ),
                        failure_message=f"Failed to process Pylon Issue: {e}",
                        exception=e,
                    )
            new_checkpoint.current_day_start = start_time
            new_checkpoint.has_more = idx < len(time_windows) - 1
        return new_checkpoint

    @override
    def build_dummy_checkpoint(self) -> PylonConnectorCheckpoint:
        """Create an initial checkpoint with work remaining."""
        return PylonConnectorCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> PylonConnectorCheckpoint:
        """Validate and deserialize a checkpoint instance from JSON."""
        return PylonConnectorCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> Iterator[list[SlimDocument]]:
        """Return document IDs for all existing Pylon issues.

        Used by the pruning job to determine which documents no longer exist
        in the source and should be removed from the index.

        Note: This fetches ALL issues without lookback filtering, as we need
        to check the existence of the issue only.

        Args:
            start: Optional start time (typically ignored for pruning)
            end: Optional end time (typically ignored for pruning)
            callback: Optional callback for progress reporting

        Yields:
            Batches of SlimDocument objects containing only document IDs
        """
        batch: list[SlimDocument] = []

        if start is not None:
            start_epoch = max(start, self.start_epoch_sec)
        else:
            start_epoch = self.start_epoch_sec
        end_epoch = end if end is not None else time.time()

        time_windows = get_time_window_days(start_epoch, end_epoch, start_epoch)
        if not time_windows:
            return

        for start_time, end_time in time_windows:
            for issue in self._iter_issues(
                start_time, end_time, messages_enabled=False, original_start=None
            ):
                if not issue.id:
                    logger.warning(
                        "Skipping issue without ID during slim doc retrieval"
                    )
                    continue

                doc_id = _create_id(issue)
                batch.append(SlimDocument(id=doc_id))

                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []

                    if callback:
                        if callback.should_stop():
                            raise RuntimeError("pylon_slim_sync: Stop signal detected")
                        callback.progress("pylon_slim_sync", len(batch))

        if batch:
            yield batch

    def validate_connector_settings(self) -> None:
        """Validate connector configuration and credentials.

        Called during connector setup to ensure everything is configured correctly.
        """
        if not self.api_key:
            raise ConnectorMissingCredentialError("Pylon")

        try:
            with self._client() as client:
                # Try a lightweight request to validate credentials
                resp = pylon_get(client, "/accounts", {"limit": 1})
                if resp.status_code == 401:
                    raise CredentialExpiredError(
                        "Invalid or expired Pylon credentials (HTTP 401)."
                    )
                if resp.status_code == 403:
                    raise InsufficientPermissionsError(
                        "Insufficient permissions to access Pylon workspace (HTTP 403)."
                    )
                if resp.status_code < 200 or resp.status_code >= 300:
                    raise UnexpectedValidationError(
                        f"Unexpected Pylon error (status={resp.status_code})."
                    )
        except Exception as e:
            # Network or other unexpected errors
            if isinstance(
                e,
                (
                    CredentialExpiredError,
                    InsufficientPermissionsError,
                    UnexpectedValidationError,
                    ConnectorMissingCredentialError,
                ),
            ):
                raise
            raise UnexpectedValidationError(
                f"Unexpected error while validating Pylon settings: {e}"
            )

    def _iter_issues(
        self,
        start_time: str,
        end_time: str,
        messages_enabled: bool,
        original_start: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[Issue]:
        """Retrieve issues from Pylon within the specified time window.

        Args:
            start_time: API request start (may be extended backwards for lookback)
            end_time: API request end
            original_start: If provided, used to fetch updated issues: last_update >= original_start (Unix epoch seconds)

        Yields:
            Issues that meet the filtering criteria
        """
        with self._client() as client:
            params = {
                "start_time": start_time,
                "end_time": end_time,
            }
            response = pylon_get(client, "/issues", params)
            response_body = GetIssuesResponseBody.model_validate(response.json())
            issues = response_body.data or []

            for issue in issues:
                # Filter by latest_message_time if lookback is used
                if original_start is not None:
                    if (
                        issue.created_at
                        and parse_pylon_datetime(issue.created_at) < original_start
                    ):
                        last_update = (
                            (issue.resolution_time or issue.latest_message_time or None)
                            if messages_enabled
                            else issue.resolution_time
                        )
                        if not last_update:
                            # No last_update means no recent activity, skip it
                            logger.debug(
                                f"Skipping issue {issue.id} - no latest_message_time during lookback"
                            )
                            continue

                        last_update_epoch = parse_pylon_datetime(last_update)

                        if last_update_epoch < original_start:
                            # last_update is before the requested start window, skip it
                            logger.debug(
                                f"Skipping issue {issue.id} - last_update {last_update} "
                                f"is before original_start"
                            )
                            continue

                yield issue

    def _iter_messages(self, issue_id: str) -> Iterator[Message]:
        """Retrieve messages for a specific issue from Pylon.

        Args:
            issue_id: The ID of the issue to fetch messages for.

        Yields:
            Message objects associated with the issue.
        """
        with self._client() as client:
            response = pylon_get(client, f"/issues/{issue_id}/messages")
            response_body = GetIssueMessagesResponseBody.model_validate(response.json())
            messages = response_body.data or []
            for message in messages:
                yield message

    def _iter_attachments(self, attachment_urls: list[str]) -> Iterator[AttachmentData]:
        """Retrieve attachments for a specific issue from Pylon.

        Args:
            attachment_urls: The URLs of the attachments to fetch.

        Yields:
            AttachmentData objects for successfully downloaded attachments.
            Skips attachments that cannot be downloaded.
        """
        with build_generic_client() as client:
            for attachment_url in attachment_urls:
                attachment_data = download_attachment(client, attachment_url)
                if attachment_data is not None:
                    yield attachment_data
