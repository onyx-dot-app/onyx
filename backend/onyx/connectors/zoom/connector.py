"""The checkpoint shell. It knows nothing about Zoom's API: each content kind
owns its own discovery, processing, and nested checkpoint state, and this
file only picks which single unit of work runs next. load_from_checkpoint is
written for the one recordings kind we have, so adding a second turns its
body into a loop over kinds.

Targeted reindex is the second entry point: it rebuilds one occurrence from
its document id, with no discovery and no checkpoint.
"""

import copy
from collections.abc import Generator
from typing import Any

from pydantic import Field

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    Resolver,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
)
from onyx.connectors.zoom.client import (
    ZoomClient,
    parse_plan_tier,
    parse_rate_limit_percent,
)
from onyx.connectors.zoom.models import ZoomSessionDetails
from onyx.connectors.zoom.recordings.access import (
    ZoomAccessListUnavailable,
    is_plan_denial,
    permanently_unavailable,
)
from onyx.connectors.zoom.recordings.discovery import build_discovery_sources
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    RecordingsState,
    ZoomSessionType,
    fails_the_whole_run,
)
from onyx.connectors.zoom.recordings.processing import (
    parse_zoom_document_id,
    process_occurrence,
)
from onyx.connectors.zoom.recordings.session_types import get_session_type_handler
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _rebuilt_work(
    client: ZoomClient,
    session_type: ZoomSessionType,
    occurrence_uuid: str,
    include_permissions: bool,
) -> OccurrenceWork:
    """Registrants, invitees and panelists hang off the session rather than the
    occurrence, and Zoom answers a wrong identifier with a 404 that reads as
    "nobody has access". So a permission-synced run that can't resolve the
    session raises rather than guess it, because guessing would index the
    document with a narrower access list than the crawl gives it.
    """
    if not include_permissions:
        return OccurrenceWork(
            session_type=session_type,
            session_id=occurrence_uuid,
            occurrence_uuid=occurrence_uuid,
        )

    handler = get_session_type_handler(session_type)
    details: ZoomSessionDetails | None
    try:
        details = handler.get_occurrence_details(client, occurrence_uuid)
    except Exception as e:
        if not permanently_unavailable(e):
            raise
        reason = (
            "the account's plan does not cover reading it"
            if is_plan_denial(e)
            else "Zoom has deleted it or it is past its retention window"
        )
        raise ZoomAccessListUnavailable(
            f"Zoom {session_type.value} occurrence {occurrence_uuid} was not "
            "reindexed because permission sync is on and the session it belongs "
            f"to could not be resolved, so its access list can't be rebuilt: "
            f"{reason}"
        ) from e

    if details is None or details.session_id is None:
        raise ZoomAccessListUnavailable(
            f"Zoom {session_type.value} occurrence {occurrence_uuid} was not "
            "reindexed because permission sync is on and Zoom no longer names "
            "the session it belongs to, so its access list can't be rebuilt"
        )

    return OccurrenceWork(
        session_type=session_type,
        session_id=details.session_id,
        occurrence_uuid=occurrence_uuid,
        start_time=details.start_time,
        topic=details.topic,
    )


class ZoomConnectorCheckpoint(ConnectorCheckpoint):
    recordings: RecordingsState = Field(default_factory=RecordingsState)


class ZoomConnector(
    CheckpointedConnectorWithPermSync[ZoomConnectorCheckpoint], Resolver
):
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
            plan_tier=parse_plan_tier(self.plan_tier),
            rate_limit_share=parse_rate_limit_percent(self.rate_limit_percent),
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

    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        if self.client is None:
            raise ConnectorMissingCredentialError("Zoom")

        for error in errors:
            failed_document = error.failed_document
            if failed_document is None:
                yield self._entity_target_unsupported(error)
                continue

            document_id = failed_document.document_id
            parsed = parse_zoom_document_id(document_id)
            if parsed is None:
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=document_id),
                    failure_message=(
                        f"'{document_id}' is not a Zoom document id this connector "
                        "wrote, so there is no occurrence to reindex"
                    ),
                )
                continue

            session_type, occurrence_uuid = parsed
            try:
                yield from process_occurrence(
                    self.client,
                    _rebuilt_work(
                        self.client, session_type, occurrence_uuid, include_permissions
                    ),
                    include_access=include_permissions,
                )
            except ZoomAccessListUnavailable as e:
                logger.warning("%s", e)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=document_id),
                    failure_message=str(e),
                    exception=e,
                )
            except Exception as e:
                # A whole batch arrives at once, so one bad target must not
                # cost the rest of them their retry.
                if fails_the_whole_run(e):
                    raise
                logger.exception("Failed to reindex Zoom document %s", document_id)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=document_id),
                    failure_message=f"Failed to reindex Zoom document {document_id}: {e}",
                    exception=e,
                )

    @staticmethod
    def _entity_target_unsupported(error: ConnectorFailure) -> ConnectorFailure:
        """Don't mint a synthetic document id to make this replayable: reindex
        would yield the real occurrence documents instead, so the synthetic id
        would never land and the row would keep failing forever.
        """
        return ConnectorFailure(
            failed_entity=error.failed_entity,
            failure_message=(
                "Zoom targeted reindex can only replay individual sessions. This "
                "failure is from discovery, so recovering it needs a wider "
                "ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS or a reindex from the beginning. "
                f"Original failure: {error.failure_message}"
            ),
        )

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
            yield from process_occurrence(
                self.client,
                state.pending_work[state.work_index],
                include_access=include_access,
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
