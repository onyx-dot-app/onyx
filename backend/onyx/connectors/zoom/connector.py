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
    GenerateSlimDocumentOutput,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.rate_limit import (
    DEFAULT_RATE_LIMIT_SHARE,
    MAX_RATE_LIMIT_PERCENT,
    MIN_RATE_LIMIT_PERCENT,
    ZoomPlanTier,
    ZoomRateLimitSettings,
)
from onyx.connectors.zoom.recordings.discovery import (
    GroupSource,
    HostAllowlistSource,
    build_discovery_sources,
)
from onyx.connectors.zoom.recordings.inventory import zoom_slim_documents
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
from onyx.connectors.zoom.recordings.recording_access import ZoomAccessContext
from onyx.connectors.zoom.validation import (
    ProbeSample,
    probe_recording_access_scopes,
    probe_zoom,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
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


def parse_session_types(
    include_meetings: Any, include_webinars: Any
) -> frozenset[ZoomSessionType]:
    """Blank means included, which is what every connector saved before these
    two checkboxes existed has to keep doing."""
    chosen: set[ZoomSessionType] = set()
    for value, session_type, name in (
        (include_meetings, ZoomSessionType.MEETING, "include_meetings"),
        (include_webinars, ZoomSessionType.WEBINAR, "include_webinars"),
    ):
        if _parse_checkbox(value, name):
            chosen.add(session_type)
    return frozenset(chosen)


def _parse_checkbox(value: Any, name: str) -> bool:
    """Blank means ticked, which keeps every connector saved before a checkbox
    existed behaving as it did."""
    if value is None:
        return True
    if not isinstance(value, bool):
        raise ValueError(f"Zoom {name} must be true or false, got {value!r}")
    return value


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


def parse_treat_link_access_as_public(value: Any) -> bool:
    """Off leaves nearly every transcript readable by its owner alone, because
    Zoom cannot say who is in "People with access", so it is the admin's
    deliberate choice and never the default."""
    return _parse_checkbox(value, "treat_link_access_as_public")


def _entity_target_unsupported(error: ConnectorFailure) -> ConnectorFailure:
    """Don't mint a synthetic document id to make this replayable: reindex
    would yield the real occurrence documents instead, so the synthetic id
    would never land and the row would keep failing forever.
    """
    return ConnectorFailure(
        failed_entity=error.failed_entity,
        failure_message=(
            "Zoom targeted reindex can only replay individual sessions. This "
            "failure is from discovery, so recovery means a wider "
            "ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS or a reindex from the "
            "beginning — neither of which reaches a session Zoom has stopped "
            "listing, which it does for a meeting id after 15 months. "
            f"Original failure: {error.failure_message}"
        ),
    )


class ZoomConnectorCheckpoint(ConnectorCheckpoint):
    recordings: RecordingsState = Field(default_factory=RecordingsState)


class ZoomConnector(
    CheckpointedConnectorWithPermSync[ZoomConnectorCheckpoint], SlimConnector, Resolver
):
    def __init__(
        self,
        meeting_ids: list[str] | None = None,
        webinar_ids: list[str] | None = None,
        host_emails: list[str] | None = None,
        group_id: str | None = None,
        plan_tier: str | None = None,
        rate_limit_percent: int | float | None = None,
        include_meetings: bool | None = None,
        include_webinars: bool | None = None,
        treat_link_access_as_public: bool | None = None,
    ) -> None:
        self._session_types = parse_session_types(include_meetings, include_webinars)
        self._treat_link_access_as_public = parse_treat_link_access_as_public(
            treat_link_access_as_public
        )
        self._sources = build_discovery_sources(
            meeting_ids, webinar_ids, host_emails, group_id, self._session_types
        )
        self._meeting_ids = meeting_ids
        self._webinar_ids = webinar_ids
        self._host_emails = host_emails
        self._group_id = group_id
        self.plan_tier = plan_tier
        self.rate_limit_percent = rate_limit_percent
        self.client: ZoomClient | None = None
        self._access: ZoomAccessContext | None = None
        # validate_connector_settings keeps what it sampled here so the
        # permission-sync probe asks about the same things instead of sampling
        # again. None means it has not run.
        self._probe_sample: ProbeSample | None = None

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
        # A sample or an access context from the old credential must not
        # outlive it.
        self._probe_sample = None
        self._access = None
        return None

    def _raise_if_nothing_is_in_scope(self) -> None:
        # Without this, a connector configured with nothing would quietly
        # index every meeting in the Zoom account.
        if not self._sources:
            raise ConnectorValidationError(
                "At least one Zoom Discovery mechanism must be configured"
            )

        # The ID lists say which type each ID is, so only a host or a Group can
        # be left with nothing to index by unticking both.
        scoped_by_type = any(
            isinstance(source, (HostAllowlistSource, GroupSource))
            for source in self._sources
        )
        if scoped_by_type and not self._session_types:
            raise ConnectorValidationError(
                "Host Emails and Zoom Group need meetings, webinars, or both included"
            )

    def validate_connector_settings(self) -> None:
        self._raise_if_nothing_is_in_scope()

        try:
            parse_plan_tier(self.plan_tier)
            parse_rate_limit_percent(self.rate_limit_percent)
        except ValueError as e:
            raise ConnectorValidationError(str(e)) from e

        self._probe_zoom()

    def _probe_zoom(self) -> ProbeSample:
        if self.client is None:
            raise ConnectorMissingCredentialError("Zoom")
        self._probe_sample = probe_zoom(
            self.client,
            meeting_ids=self._meeting_ids,
            webinar_ids=self._webinar_ids,
            host_emails=self._host_emails,
            group_id=self._group_id,
        )
        return self._probe_sample

    def probe_recording_access_permissions(self) -> None:
        """A missing permission-sync scope would otherwise index every transcript
        as readable by its owner alone, with nothing to say why. Reuses the
        recording validate_connector_settings sampled, or samples if that has
        not run.
        """
        if self.client is None:
            raise ConnectorMissingCredentialError("Zoom")
        sample = self._probe_sample or self._probe_zoom()
        probe_recording_access_scopes(self.client, sample)

    def build_dummy_checkpoint(self) -> ZoomConnectorCheckpoint:
        return ZoomConnectorCheckpoint(has_more=True)

    def _access_for(self, include_access: bool) -> ZoomAccessContext | None:
        """One per run, so each owner and the rule catalogue are asked for once."""
        if not include_access:
            return None
        if self.client is None:
            raise ConnectorMissingCredentialError("Zoom")
        if self._access is None:
            self._access = ZoomAccessContext(
                self.client, self._treat_link_access_as_public
            )
        return self._access

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

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        """Pruning deletes every indexed document this does not list, so the poll
        window is ignored and the callback is not needed: the caller drives its
        own heartbeat off the batches.

        Not SlimConnectorWithPermSync. Zoom builds its access lists while
        indexing, so pruning wants ids and nothing else.
        """
        if self.client is None:
            raise ConnectorMissingCredentialError("Zoom")
        # Checked again here because instantiate_connector skips
        # validate_connector_settings, so a connector saved with a blank form
        # would reach this, list nothing, and delete everything it indexed.
        self._raise_if_nothing_is_in_scope()
        return zoom_slim_documents(self.client, self._sources)

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
                yield _entity_target_unsupported(error)
                continue

            document_id = failed_document.document_id
            parsed = parse_zoom_document_id(document_id)
            if parsed is None:
                logger.error(
                    "Zoom targeted reindex was handed an id it did not write: %s",
                    document_id,
                )
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=document_id),
                    failure_message=(
                        f"'{document_id}' is not a Zoom document id this connector "
                        "wrote, so there is no occurrence to reindex"
                    ),
                )
                continue

            session_type, occurrence_uuid = parsed
            # The occurrence UUID is all a rebuild needs: the recording, its
            # transcript and its share settings all answer for it, and the
            # session it belongs to only ever supplied a title.
            work = OccurrenceWork(
                session_type=session_type,
                session_id=occurrence_uuid,
                occurrence_uuid=occurrence_uuid,
            )
            try:
                processed = process_occurrence(
                    self.client, work, access=self._access_for(include_permissions)
                )
                if processed is not None:
                    yield processed
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
                access=self._access_for(include_access),
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
