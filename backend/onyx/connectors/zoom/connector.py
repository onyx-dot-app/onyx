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
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorMissingCredentialError,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.rate_limit import (
    DEFAULT_RATE_LIMIT_SHARE,
    MAX_RATE_LIMIT_PERCENT,
    MIN_RATE_LIMIT_PERCENT,
    ZoomPlanTier,
    ZoomRateLimitSettings,
)
from onyx.connectors.zoom.recordings.discovery import build_discovery_sources
from onyx.connectors.zoom.recordings.models import RecordingsState
from onyx.connectors.zoom.recordings.processing import process_occurrence
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Nothing between the API and here checks the type of a stored config value,
# and only a ValueError becomes a message the admin can read.


def parse_plan_tier(value: Any) -> ZoomPlanTier:
    """Blank means Pro, the lowest plan this connector supports, because
    guessing high spends an allowance the account may not have."""
    if value is None:
        return ZoomPlanTier.PRO
    if not isinstance(value, str):
        raise ValueError(f"Zoom plan must be text, got {value!r}")
    if not value.strip():
        return ZoomPlanTier.PRO
    try:
        return ZoomPlanTier(value.strip().lower())
    except ValueError as e:
        known = ", ".join(plan.value for plan in ZoomPlanTier)
        raise ValueError(f"Unknown Zoom plan {value!r}. Use one of: {known}") from e


def parse_rate_limit_percent(value: Any) -> float:
    if value is None:
        return DEFAULT_RATE_LIMIT_SHARE
    # bool is an int in Python, so True would otherwise pass as 1 percent and
    # throttle the connector to a single call per second.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Zoom rate limit percent must be a number, got {value!r}")
    if not MIN_RATE_LIMIT_PERCENT <= value <= MAX_RATE_LIMIT_PERCENT:
        raise ValueError(
            f"Zoom rate limit percent must be between {MIN_RATE_LIMIT_PERCENT} "
            f"and {MAX_RATE_LIMIT_PERCENT}, got {value}"
        )
    return value / 100


class ZoomConnectorCheckpoint(ConnectorCheckpoint):
    recordings: RecordingsState = Field(default_factory=RecordingsState)


class ZoomConnector(CheckpointedConnectorWithPermSync[ZoomConnectorCheckpoint]):
    def __init__(
        self,
        meeting_ids: list[str] | None = None,
        webinar_ids: list[str] | None = None,
        host_emails: list[str] | None = None,
        group_id: str | None = None,
        plan_tier: str | None = None,
        rate_limit_percent: int | float | None = None,
    ) -> None:
        self._sources = build_discovery_sources(
            meeting_ids, webinar_ids, host_emails, group_id
        )
        self.plan_tier = plan_tier
        self.rate_limit_percent = rate_limit_percent
        self.client: ZoomClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        account_id = credentials.get("zoom_account_id")
        client_id = credentials.get("zoom_client_id")
        client_secret = credentials.get("zoom_client_secret")

        if not account_id or not client_id or not client_secret:
            raise ConnectorMissingCredentialError("Zoom")

        self.client = ZoomClient(
            account_id=account_id,
            client_id=client_id,
            client_secret=client_secret,
            rate_limit_settings=ZoomRateLimitSettings(
                plan_tier=parse_plan_tier(self.plan_tier),
                share=parse_rate_limit_percent(self.rate_limit_percent),
            ),
        )
        return None

    def validate_connector_settings(self) -> None:
        # Without this, a connector configured with nothing would quietly
        # index every meeting in the Zoom account.
        if not self._sources:
            raise ConnectorValidationError(
                "At least one Zoom Discovery mechanism must be configured"
            )

        try:
            parse_plan_tier(self.plan_tier)
            parse_rate_limit_percent(self.rate_limit_percent)
        except ValueError as e:
            raise ConnectorValidationError(str(e)) from e

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
        # Don't collapse this into the method below: a connector that is not
        # permission synced would then pay two or three extra Zoom calls per
        # document for an access list it cannot use.
        return self._advance(start, end, checkpoint, include_access=False)

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ZoomConnectorCheckpoint,
    ) -> CheckpointOutput[ZoomConnectorCheckpoint]:
        return self._advance(start, end, checkpoint, include_access=True)

    def _advance(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ZoomConnectorCheckpoint,
        *,
        include_access: bool,
    ) -> CheckpointOutput[ZoomConnectorCheckpoint]:
        if self.client is None:
            raise ConnectorMissingCredentialError("Zoom")

        checkpoint = copy.deepcopy(checkpoint)
        state = checkpoint.recordings

        if state.work_index < len(state.pending_work):
            processed = process_occurrence(
                self.client,
                state.pending_work[state.work_index],
                include_access=include_access,
            )
            if processed is not None:
                yield processed
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
