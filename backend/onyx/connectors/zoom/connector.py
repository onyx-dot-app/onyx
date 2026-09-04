"""The checkpoint shell. It knows nothing about Zoom's API: each content kind
owns its own discovery, processing, and nested checkpoint state, and this
file only picks which single unit of work runs next. load_from_checkpoint is
written for the one recordings kind we have, so adding a second turns its
body into a loop over kinds.
"""

import copy
from typing import Any

from pydantic import Field

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorMissingCredentialError,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.recordings.discovery import build_discovery_sources
from onyx.connectors.zoom.recordings.models import RecordingsState
from onyx.connectors.zoom.recordings.processing import process_occurrence
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ZoomConnectorCheckpoint(ConnectorCheckpoint):
    recordings: RecordingsState = Field(default_factory=RecordingsState)


class ZoomConnector(CheckpointedConnector[ZoomConnectorCheckpoint]):
    def __init__(self, meeting_ids: list[str] | None = None) -> None:
        self._sources = build_discovery_sources(meeting_ids)
        self.client: ZoomClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        account_id = credentials.get("zoom_account_id")
        client_id = credentials.get("zoom_client_id")
        client_secret = credentials.get("zoom_client_secret")

        if not account_id or not client_id or not client_secret:
            raise ConnectorMissingCredentialError("Zoom")

        self.client = ZoomClient(
            account_id=account_id, client_id=client_id, client_secret=client_secret
        )
        return None

    def validate_connector_settings(self) -> None:
        # Without this, a connector configured with nothing would quietly
        # index every meeting in the Zoom account.
        if not self._sources:
            raise ConnectorValidationError(
                "At least one Zoom Discovery mechanism must be configured"
            )

    def build_dummy_checkpoint(self) -> ZoomConnectorCheckpoint:
        return ZoomConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ZoomConnectorCheckpoint:
        return ZoomConnectorCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ZoomConnectorCheckpoint,
    ) -> CheckpointOutput[ZoomConnectorCheckpoint]:
        if self.client is None:
            raise ConnectorMissingCredentialError("Zoom")

        checkpoint = copy.deepcopy(checkpoint)
        state = checkpoint.recordings

        if state.work_index < len(state.pending_work):
            yield from process_occurrence(
                self.client, state.pending_work[state.work_index]
            )
            state.work_index += 1
        elif state.source_index < len(self._sources):
            source = self._sources[state.source_index]
            result = source.discover_step(self.client, start, end, state.source_cursor)
            yield from result.failures
            state.pending_work = result.work
            state.work_index = 0
            if result.done:
                state.source_index += 1
                state.source_cursor = None
            else:
                state.source_cursor = result.next_cursor

        checkpoint.has_more = state.work_index < len(
            state.pending_work
        ) or state.source_index < len(self._sources)
        return checkpoint
