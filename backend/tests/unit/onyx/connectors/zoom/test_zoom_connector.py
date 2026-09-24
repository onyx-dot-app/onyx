import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, cast
from unittest.mock import MagicMock, patch

import pytest
import requests
from sqlalchemy.orm import Session

from onyx.auth.permissions import Permission
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    InputType,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.connector import ZoomConnector, ZoomConnectorCheckpoint
from onyx.connectors.zoom.models import (
    ZoomRecordingEntry,
    ZoomRecordingPage,
    ZoomSessionOccurrence,
    ZoomTranscript,
    ZoomUser,
    ZoomUserPage,
)
from onyx.connectors.zoom.rate_limit import (
    DEFAULT_RATE_LIMIT_SHARE,
    ZoomPlanTier,
    ZoomRateLimitSettings,
)
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    RecordingsState,
    ZoomSessionType,
)
from onyx.db.enums import AccessType
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import connector as connector_router
from onyx.server.documents.connector import (
    create_connector_from_model,
    create_connector_with_mock_credential,
)
from onyx.server.documents.models import (
    ConnectorBase,
    ConnectorUpdateRequest,
    ObjectCreationIdResponse,
)
from tests.unit.onyx.connectors.utils import (
    _ITERATION_LIMIT,
    load_everything_from_checkpoint_connector,
    load_everything_from_checkpoint_connector_from_checkpoint,
)
from tests.unit.onyx.connectors.zoom.helpers import SAMPLE_VTT, mock_zoom_client
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    invitee,
    participant,
    past_meeting_details,
    recording_entry,
    registrant,
    transcript,
    user,
    webinar_details,
)

_ZOOM_CREDS = {
    "zoom_account_id": "test-account",
    "zoom_client_id": "test-client-id",
    "zoom_client_secret": "test-client-secret",
}

_FULL_HISTORY_END = time.time()

_OLDEST_OCCURRENCE_DAYS_AGO = 21

# An epoch start would split into hundreds of 30-day windows per host. Derived from
# the oldest occurrence rather than picked, so the window holds it even where
# ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS is set to zero and widens the start by nothing.
_POLL_START = _FULL_HISTORY_END - (_OLDEST_OCCURRENCE_DAYS_AGO + 1) * 24 * 60 * 60


def _days_ago(days: int) -> str:
    # Build these off the same clock as _FULL_HISTORY_END. A pinned calendar date
    # falls outside the poll window on a machine whose clock is older, and every
    # test then silently gets an empty result set.
    moment = datetime.fromtimestamp(_FULL_HISTORY_END, tz=timezone.utc) - timedelta(
        days=days
    )
    return moment.isoformat()


def _make_connector(
    meeting_ids: list[str] | None = None,
    webinar_ids: list[str] | None = None,
    host_emails: list[str] | None = None,
    group_id: str | None = None,
) -> tuple[ZoomConnector, MagicMock]:
    # Don't write `meeting_ids or [...]` here: it swaps a caller's empty list
    # for the default, and the empty-allowlist tests below then pass for the
    # wrong reason.
    connector = ZoomConnector(
        meeting_ids=["111"] if meeting_ids is None else meeting_ids,
        webinar_ids=webinar_ids,
        host_emails=host_emails,
        group_id=group_id,
    )
    connector.load_credentials(_ZOOM_CREDS)
    mock_client = mock_zoom_client()
    connector.client = mock_client
    return connector, mock_client


def _configure_happy_path(mock_client: MagicMock) -> None:
    mock_client.list_past_meeting_occurrences.side_effect = (
        lambda session_id, *_window: [
            ZoomSessionOccurrence(uuid=f"uuid-{session_id}", start_time=_days_ago(7))
        ]
    )
    mock_client.get_meeting_transcript.side_effect = lambda uuid: transcript(
        download_url=f"https://zoom.example/{uuid}.vtt",
        meeting_topic="Recorded Session",
    )
    mock_client.download_transcript_vtt.return_value = SAMPLE_VTT
    mock_client.get_past_meeting_details.return_value = past_meeting_details(
        topic="Weekly Sync"
    )
    mock_client.list_past_webinar_occurrences.side_effect = lambda session_id: [
        ZoomSessionOccurrence(uuid=f"uuid-{session_id}", start_time=_days_ago(7))
    ]
    mock_client.get_webinar_details.return_value = webinar_details(
        topic="Product Launch"
    )


def _transcript_without_a_topic(mock_client: MagicMock) -> None:
    """Zoom names the session in the transcript response, so the details
    endpoints are only reached when it doesn't."""
    mock_client.get_meeting_transcript.side_effect = lambda uuid: transcript(
        download_url=f"https://zoom.example/{uuid}.vtt", meeting_topic=""
    )


class TestZoomConnectorCredentials:
    def test_load_credentials_requires_all_fields(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        with pytest.raises(ConnectorMissingCredentialError):
            connector.load_credentials({"zoom_account_id": "only-one-field"})

    def test_load_from_checkpoint_without_credentials_raises(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        checkpoint = connector.build_dummy_checkpoint()
        with pytest.raises(ConnectorMissingCredentialError):
            next(connector.load_from_checkpoint(0, 1, checkpoint))

    def test_reindex_without_credentials_raises(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        with pytest.raises(ConnectorMissingCredentialError):
            next(connector.reindex(errors=[]))

    @pytest.mark.parametrize(
        "plan, percent, expected_plan, expected_share",
        [
            (None, None, ZoomPlanTier.PRO, DEFAULT_RATE_LIMIT_SHARE),
            ("business_plus", 10, ZoomPlanTier.BUSINESS_PLUS, 0.1),
        ],
        ids=["unset falls back to the defaults", "configured"],
    )
    def test_the_configured_rate_limits_reach_the_client(
        self,
        plan: str | None,
        percent: int | None,
        expected_plan: ZoomPlanTier,
        expected_share: float,
    ) -> None:
        connector = ZoomConnector(
            meeting_ids=["111"], plan_tier=plan, rate_limit_percent=percent
        )

        with patch.object(ZoomClient, "__init__", return_value=None) as build:
            connector.load_credentials(_ZOOM_CREDS)

        settings = build.call_args.kwargs["rate_limit_settings"]
        assert settings == ZoomRateLimitSettings(
            plan_tier=expected_plan, share=expected_share
        )


class TestPruningDrivesTheConnectorFromTheEpoch:
    """extract_ids_from_runnable_connector drives load_from_checkpoint with a
    hardcoded epoch start. Rejecting that start stops pruning before it names a
    single document, on every Zoom connector, every week."""

    def test_an_epoch_start_still_runs(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)

        outputs = load_everything_from_checkpoint_connector(
            connector, 0, _FULL_HISTORY_END
        )

        documents = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]
        assert [d.id for d in documents] == ["ZOOM_MEETING_uuid-111"]


class TestIndexingStartIsRequiredAtConfigTime:
    """Enforced where the connector cannot: the class above is why a start date
    cannot be demanded at index time. These drive the endpoints an admin posts to
    rather than the check itself, which an endpoint could quietly stop calling.
    """

    _START = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _ENDPOINTS = [create_connector_from_model, create_connector_with_mock_credential]

    @staticmethod
    def _admin() -> User:
        user = MagicMock()
        user.effective_permissions = [Permission.FULL_ADMIN_PANEL_ACCESS.value]
        return cast(User, user)

    @staticmethod
    @contextmanager
    def _rows_written() -> Generator[list[ConnectorBase]]:
        """Stands in for the row write, so what an endpoint forwards can be read
        back without a database."""
        written: list[ConnectorBase] = []

        def create(
            db_session: Session,  # noqa: ARG001
            connector_data: ConnectorBase,
        ) -> ObjectCreationIdResponse:
            written.append(connector_data)
            return ObjectCreationIdResponse(id=1)

        with patch.object(connector_router, "create_connector", create):
            yield written

    def _post(
        self,
        endpoint: Callable[..., Any],
        source: DocumentSource = DocumentSource.ZOOM,
        indexing_start: datetime | None = None,
    ) -> None:
        endpoint(
            ConnectorUpdateRequest(
                name="test",
                source=source,
                input_type=InputType.POLL,
                connector_specific_config={},
                indexing_start=indexing_start,
                access_type=AccessType.PUBLIC,
            ),
            user=self._admin(),
            db_session=cast(Session, MagicMock(spec=Session)),
        )

    @pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=["connector", "mock-cred"])
    def test_zoom_without_a_start_date_never_reaches_the_row(
        self, endpoint: Callable[..., Any]
    ) -> None:
        with self._rows_written() as written:
            with pytest.raises(OnyxError) as raised:
                self._post(endpoint)

        assert raised.value.error_code is OnyxErrorCode.INVALID_INPUT
        assert written == []

    # Only the plain endpoint: the mock-credential one carries on into credential
    # creation and a Celery dispatch that a stubbed session cannot answer for.
    def test_the_start_date_an_admin_sets_is_the_one_stored(self) -> None:
        """Demanding a date buys nothing if the endpoint then drops it, which is
        exactly what the update path did."""
        with self._rows_written() as written:
            self._post(create_connector_from_model, indexing_start=self._START)

        assert [row.indexing_start for row in written] == [self._START]

    def test_another_source_still_creates_without_one(self) -> None:
        with self._rows_written() as written:
            self._post(create_connector_from_model, source=DocumentSource.CONFLUENCE)

        assert [row.indexing_start for row in written] == [None]


class TestZoomConnectorValidateSettings:
    def test_no_discovery_mechanism_rejected(self) -> None:
        connector = ZoomConnector(meeting_ids=[])
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    def test_configured_meeting_ids_accepted(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        connector.validate_connector_settings()

    def test_webinar_ids_alone_are_a_discovery_mechanism(self) -> None:
        connector = ZoomConnector(webinar_ids=["222"])
        connector.validate_connector_settings()

    def test_host_emails_alone_are_a_discovery_mechanism(self) -> None:
        connector = ZoomConnector(host_emails=["host@example.com"])
        connector.validate_connector_settings()

    def test_a_group_alone_is_a_discovery_mechanism(self) -> None:
        connector = ZoomConnector(group_id="group-1")
        connector.validate_connector_settings()

    def test_all_three_mechanisms_empty_is_rejected(self) -> None:
        connector = ZoomConnector(
            meeting_ids=[], webinar_ids=[], host_emails=[], group_id=None
        )
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    def test_fields_left_blank_are_not_a_discovery_mechanism(self) -> None:
        # An admin who clears a field leaves whitespace behind, and accepting
        # that is what would start a full-organization crawl.
        connector = ZoomConnector(host_emails=["  "], group_id="  ")
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    def test_an_unknown_plan_is_rejected_at_setup(self) -> None:
        # Without this check a typo reaches the client and crashes mid-backfill,
        # where no admin sees it.
        connector = ZoomConnector(meeting_ids=["111"], plan_tier="enterprise")
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    @pytest.mark.parametrize("percent", [0, 101])
    def test_a_rate_limit_percent_outside_the_range_is_rejected(
        self, percent: int
    ) -> None:
        connector = ZoomConnector(meeting_ids=["111"], rate_limit_percent=percent)
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    @pytest.mark.parametrize("percent", ["50", True])
    def test_a_rate_limit_percent_of_the_wrong_type_is_rejected(
        self, percent: Any
    ) -> None:
        connector = ZoomConnector(meeting_ids=["111"], rate_limit_percent=percent)
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    @pytest.mark.parametrize("plan", [5, ["pro"]])
    def test_a_plan_that_is_not_text_is_rejected(self, plan: Any) -> None:
        connector = ZoomConnector(meeting_ids=["111"], plan_tier=plan)
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()


class TestZoomConnectorCheckpoint:
    def test_build_dummy_checkpoint(self) -> None:
        connector, _ = _make_connector()
        checkpoint = connector.build_dummy_checkpoint()
        assert checkpoint.has_more is True
        assert checkpoint.recordings == RecordingsState()

    def test_validate_checkpoint_json(self) -> None:
        connector, _ = _make_connector()
        original = ZoomConnectorCheckpoint(
            has_more=True,
            recordings=RecordingsState(
                source_index=1,
                source_cursor={"index": 2},
                pending_work=[
                    OccurrenceWork(
                        session_type=ZoomSessionType.MEETING,
                        session_id="111",
                        occurrence_uuid="uuid-1",
                    )
                ],
                work_index=1,
            ),
        )
        restored = connector.validate_checkpoint_json(original.model_dump_json())
        assert restored == original

    def test_recorded_meeting_becomes_document_end_to_end(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        # One invocation to discover the occurrence, one to process it.
        assert len(outputs) == 2
        assert len(docs) == 1
        doc = docs[0]
        # Assert on the occurrence UUID, not the meeting id: passing the bare
        # meeting id would silently index only the most recent occurrence.
        assert doc.id == "ZOOM_MEETING_uuid-111"
        mock_client.get_meeting_transcript.assert_called_once_with("uuid-111")
        # The transcript names the session, so the details endpoint — and the
        # one-year cap that comes with it — is never reached.
        assert doc.semantic_identifier == "Recorded Session"
        mock_client.get_past_meeting_details.assert_not_called()
        assert doc.metadata == {"session_type": "meeting"}
        assert outputs[-1].next_checkpoint.has_more is False

    def test_recurring_meeting_yields_one_document_per_occurrence(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)
        mock_client.list_past_meeting_occurrences.side_effect = None
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomSessionOccurrence(
                uuid="uuid-1", start_time=_days_ago(_OLDEST_OCCURRENCE_DAYS_AGO)
            ),
            ZoomSessionOccurrence(uuid="uuid-2", start_time=_days_ago(14)),
            ZoomSessionOccurrence(uuid="uuid-3", start_time=_days_ago(7)),
        ]

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-1",
            "ZOOM_MEETING_uuid-2",
            "ZOOM_MEETING_uuid-3",
        ]
        assert outputs[-1].next_checkpoint.has_more is False

    def test_one_failing_occurrence_does_not_block_the_others(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)
        mock_client.list_past_meeting_occurrences.side_effect = None
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomSessionOccurrence(
                uuid="uuid-1", start_time=_days_ago(_OLDEST_OCCURRENCE_DAYS_AGO)
            ),
            ZoomSessionOccurrence(uuid="uuid-2", start_time=_days_ago(14)),
            ZoomSessionOccurrence(uuid="uuid-3", start_time=_days_ago(7)),
        ]

        def _transcript(uuid: str) -> ZoomTranscript:
            if uuid == "uuid-2":
                raise RuntimeError("boom")
            return transcript(download_url=f"https://zoom.example/{uuid}.vtt")

        mock_client.get_meeting_transcript.side_effect = _transcript

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        items = [item for output in outputs for item in output.items]
        docs = [item for item in items if isinstance(item, Document)]
        failures = [item for item in items if isinstance(item, ConnectorFailure)]

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-1",
            "ZOOM_MEETING_uuid-3",
        ]
        assert len(failures) == 1
        assert failures[0].failed_document is not None
        assert failures[0].failed_document.document_id == "ZOOM_MEETING_uuid-2"
        assert outputs[-1].next_checkpoint.has_more is False

    def test_failing_id_does_not_block_the_next_id(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111", "222"])
        _configure_happy_path(mock_client)

        def _occurrences(
            session_id: str, *_window: datetime
        ) -> list[ZoomSessionOccurrence]:
            if session_id == "111":
                raise RuntimeError("boom")
            return [
                ZoomSessionOccurrence(
                    uuid=f"uuid-{session_id}", start_time=_days_ago(7)
                )
            ]

        mock_client.list_past_meeting_occurrences.side_effect = _occurrences

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        items = [item for output in outputs for item in output.items]
        docs = [item for item in items if isinstance(item, Document)]
        failures = [item for item in items if isinstance(item, ConnectorFailure)]

        assert [d.id for d in docs] == ["ZOOM_MEETING_uuid-222"]
        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert failures[0].failed_entity.entity_id == "meeting:111"
        assert outputs[-1].next_checkpoint.has_more is False

    def test_meeting_with_no_occurrences_completes_without_documents(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        mock_client.list_past_meeting_occurrences.return_value = []

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )

        assert all(output.items == [] for output in outputs)
        mock_client.get_meeting_transcript.assert_not_called()
        assert outputs[-1].next_checkpoint.has_more is False

    def test_discovery_failure_surfaces_as_connector_failure(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        mock_client.list_past_meeting_occurrences.side_effect = RuntimeError("boom")

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        failures = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, ConnectorFailure)
        ]

        assert len(failures) == 1
        assert failures[0].failed_entity is not None
        assert failures[0].failed_entity.entity_id == "meeting:111"
        assert outputs[-1].next_checkpoint.has_more is False

    def test_iterates_multiple_meeting_ids_across_checkpoint_calls(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111", "222"])
        _configure_happy_path(mock_client)

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )

        # Discover and process each of the two ids in turn.
        assert len(outputs) == 4
        assert outputs[-1].next_checkpoint.has_more is False

        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]
        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-111",
            "ZOOM_MEETING_uuid-222",
        ]

    def test_resumes_mid_run_from_serialized_checkpoint(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111", "222"])
        _configure_happy_path(mock_client)

        # The real worker serializes the checkpoint between invocations, so round-trip
        # it through JSON here and finish the run from the restored copy.
        checkpoint = connector.build_dummy_checkpoint()
        generator = connector.load_from_checkpoint(
            _POLL_START, _FULL_HISTORY_END, checkpoint
        )
        try:
            while True:
                next(generator)
        except StopIteration as e:
            checkpoint = e.value
        restored = connector.validate_checkpoint_json(checkpoint.model_dump_json())

        outputs = load_everything_from_checkpoint_connector_from_checkpoint(
            connector, _POLL_START, _FULL_HISTORY_END, restored
        )
        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-111",
            "ZOOM_MEETING_uuid-222",
        ]
        assert outputs[-1].next_checkpoint.has_more is False

    def test_no_meeting_ids_completes_immediately(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=[])

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )

        assert len(outputs) == 1
        assert outputs[0].items == []
        assert outputs[0].next_checkpoint.has_more is False
        mock_client.list_past_meeting_occurrences.assert_not_called()


class TestSystemicFailureDoesNotAdvanceWork:
    """work_index advances as soon as an occurrence is processed. A rate limit
    has to leave it alone, or the next run starts past the occurrence that
    never got indexed."""

    def _checkpoint(self) -> ZoomConnectorCheckpoint:
        return ZoomConnectorCheckpoint(
            has_more=True,
            recordings=RecordingsState(
                pending_work=[
                    OccurrenceWork(
                        session_type=ZoomSessionType.MEETING,
                        session_id="111",
                        occurrence_uuid=uuid,
                    )
                    for uuid in ("uuid-1", "uuid-2")
                ],
                work_index=0,
            ),
        )

    def test_rate_limit_raises_instead_of_advancing_past_the_occurrence(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        response = requests.Response()
        response.status_code = 429
        mock_client.get_meeting_transcript.side_effect = requests.HTTPError(
            "429", response=response
        )

        emitted = 0
        generator = connector.load_from_checkpoint(
            _POLL_START, _FULL_HISTORY_END, self._checkpoint()
        )
        with pytest.raises(requests.HTTPError):
            for _ in generator:
                emitted += 1

        # Recording a failure here instead would let the attempt finish, and the
        # checkpoint it saved would point past the occurrence that never indexed.
        assert emitted == 0

    def test_a_document_specific_failure_still_advances(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        response = requests.Response()
        response.status_code = 400
        mock_client.get_meeting_transcript.side_effect = requests.HTTPError(
            "400", response=response
        )

        generator = connector.load_from_checkpoint(
            _POLL_START, _FULL_HISTORY_END, self._checkpoint()
        )
        items: list[Document | HierarchyNode | ConnectorFailure] = []
        try:
            while True:
                items.append(next(generator))
        except StopIteration as stop:
            returned = stop.value

        assert [isinstance(item, ConnectorFailure) for item in items] == [True]
        assert returned.recordings.work_index == 1

    def test_a_session_without_a_transcript_advances_without_a_failure(self) -> None:
        # Reporting each untranscribed session would end every run
        # COMPLETED_WITH_ERRORS and bury the real failures.
        connector, mock_client = _make_connector(meeting_ids=["111"])
        response = requests.Response()
        response.status_code = 404
        mock_client.get_meeting_transcript.side_effect = requests.HTTPError(
            "404", response=response
        )

        generator = connector.load_from_checkpoint(
            _POLL_START, _FULL_HISTORY_END, self._checkpoint()
        )
        emitted = 0
        try:
            while True:
                next(generator)
                emitted += 1
        except StopIteration as stop:
            returned = stop.value

        assert emitted == 0
        assert returned.recordings.work_index == 1


class TestSessionSourceTypes:
    """The admin picks Meeting only, Webinar only, or Both at setup, so
    nothing has to detect a session's type at runtime."""

    def _documents(self, connector: ZoomConnector) -> list[Document]:
        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        assert outputs[-1].next_checkpoint.has_more is False
        return [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

    def test_meeting_only_never_calls_a_webinar_endpoint(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        _configure_happy_path(mock_client)

        docs = self._documents(connector)

        assert [d.id for d in docs] == ["ZOOM_MEETING_uuid-111"]
        mock_client.list_past_webinar_occurrences.assert_not_called()

    def test_webinar_only_indexes_a_tagged_webinar_document(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=[], webinar_ids=["222"])
        _configure_happy_path(mock_client)

        docs = self._documents(connector)

        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "ZOOM_WEBINAR_uuid-222"
        assert doc.metadata == {"session_type": "webinar"}
        assert doc.semantic_identifier == "Recorded Session"
        mock_client.get_webinar_details.assert_not_called()
        # A webinar's transcript comes from the meeting endpoint; Zoom has no
        # webinar one.
        mock_client.get_meeting_transcript.assert_called_once_with("uuid-222")
        mock_client.list_past_meeting_occurrences.assert_not_called()

    def test_both_dispatches_each_id_to_its_own_endpoint(self) -> None:
        connector, mock_client = _make_connector(
            meeting_ids=["111"], webinar_ids=["222"]
        )
        _configure_happy_path(mock_client)

        docs = self._documents(connector)

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-111",
            "ZOOM_WEBINAR_uuid-222",
        ]
        assert [d.metadata["session_type"] for d in docs] == ["meeting", "webinar"]
        # The meeting endpoint also takes the poll window; only the id matters here.
        assert mock_client.list_past_meeting_occurrences.call_args.args[0] == "111"
        mock_client.list_past_webinar_occurrences.assert_called_once_with("222")

    def test_the_same_id_in_both_fields_is_indexed_as_two_documents(self) -> None:
        # The same number can be a meeting id and a webinar id, and those are
        # two different sessions.
        connector, mock_client = _make_connector(
            meeting_ids=["111"], webinar_ids=["111"]
        )
        _configure_happy_path(mock_client)
        mock_client.list_past_meeting_occurrences.side_effect = None
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomSessionOccurrence(uuid="shared-uuid", start_time=_days_ago(7))
        ]
        mock_client.list_past_webinar_occurrences.side_effect = None
        mock_client.list_past_webinar_occurrences.return_value = [
            ZoomSessionOccurrence(uuid="shared-uuid", start_time=_days_ago(7))
        ]

        docs = self._documents(connector)

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_shared-uuid",
            "ZOOM_WEBINAR_shared-uuid",
        ]

    def test_a_titleless_webinar_falls_back_to_its_own_details_endpoint(
        self,
    ) -> None:
        connector, mock_client = _make_connector(meeting_ids=[], webinar_ids=["222"])
        _configure_happy_path(mock_client)
        _transcript_without_a_topic(mock_client)

        docs = self._documents(connector)

        assert docs[0].semantic_identifier == "Product Launch"
        mock_client.get_webinar_details.assert_called_once_with("uuid-222")
        mock_client.get_past_meeting_details.assert_not_called()

    def test_a_webinar_without_a_title_is_not_labelled_a_meeting(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=[], webinar_ids=["222"])
        _configure_happy_path(mock_client)
        _transcript_without_a_topic(mock_client)
        mock_client.get_webinar_details.return_value = None

        docs = self._documents(connector)

        assert docs[0].semantic_identifier == "Zoom Webinar 222"


def _recording(
    uuid: str,
    session_id: int = 6840331990,
    topic: str = "Weekly Sync",
    recording_type: str = "2",
) -> ZoomRecordingEntry:
    # The poll window is measured off the same clock as _FULL_HISTORY_END, so
    # these timestamps have to be relative rather than a pinned date.
    return recording_entry(
        uuid=uuid,
        id=session_id,
        topic=topic,
        start_time=_days_ago(7),
        type=recording_type,
    )


def _configure_user_recordings(
    mock_client: MagicMock,
    recordings_by_user: dict[str, list[ZoomRecordingEntry]],
    members: list[ZoomUser] | None = None,
) -> None:
    mock_client.list_users.return_value = ZoomUserPage(
        users=[
            user(id="host-user", email="host@example.com"),
            user(id="member-user", email="member@example.com"),
        ]
    )
    mock_client.list_group_members.return_value = ZoomUserPage(
        users=(
            [user(id="member-user", email="member@example.com")]
            if members is None
            else members
        )
    )
    mock_client.list_user_recordings.side_effect = lambda user_id, **_: (
        ZoomRecordingPage(recordings=recordings_by_user.get(user_id, []))
    )


class TestDiscoveryMechanismUnion:
    """An admin turns on any mix of the three mechanisms and gets the union, each
    one walking its own cursor in turn."""

    def _documents(self, connector: ZoomConnector) -> list[Document]:
        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        assert outputs[-1].next_checkpoint.has_more is False
        return [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

    def test_a_host_allowlist_indexes_that_hosts_sessions(self) -> None:
        connector, mock_client = _make_connector(
            meeting_ids=[], host_emails=["host@example.com"]
        )
        _configure_happy_path(mock_client)
        _configure_user_recordings(
            mock_client,
            {
                "host-user": [
                    _recording("uuid-town-hall", topic="Town Hall"),
                    _recording("uuid-webinar", topic="Launch", recording_type="5"),
                ]
            },
        )

        docs = self._documents(connector)

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-town-hall",
            "ZOOM_WEBINAR_uuid-webinar",
        ]
        assert [d.metadata["session_type"] for d in docs] == ["meeting", "webinar"]
        # The listing already named both sessions, so neither details endpoint —
        # nor the age cap each one carries — is ever reached.
        assert [d.semantic_identifier for d in docs] == ["Town Hall", "Launch"]
        mock_client.get_past_meeting_details.assert_not_called()
        mock_client.get_webinar_details.assert_not_called()

    def test_a_group_indexes_every_members_sessions(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=[], group_id="group-1")
        _configure_happy_path(mock_client)
        _configure_user_recordings(
            mock_client, {"member-user": [_recording("uuid-standup")]}
        )

        docs = self._documents(connector)

        assert [d.id for d in docs] == ["ZOOM_MEETING_uuid-standup"]
        mock_client.list_group_members.assert_called_once_with(
            "group-1", page_token=None
        )

    def test_all_three_mechanisms_union_into_one_run(self) -> None:
        connector, mock_client = _make_connector(
            meeting_ids=["111"],
            host_emails=["host@example.com"],
            group_id="group-1",
        )
        _configure_happy_path(mock_client)
        _configure_user_recordings(
            mock_client,
            {
                "host-user": [_recording("uuid-host")],
                "member-user": [_recording("uuid-member")],
            },
        )

        docs = self._documents(connector)

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-111",
            "ZOOM_MEETING_uuid-host",
            "ZOOM_MEETING_uuid-member",
        ]

    def test_an_occurrence_two_mechanisms_both_reach_keeps_one_identity(self) -> None:
        # Nothing dedupes across mechanisms, because a document is keyed by its
        # occurrence uuid and the upsert makes the second copy a no-op.
        connector, mock_client = _make_connector(
            meeting_ids=[], host_emails=["host@example.com"], group_id="group-1"
        )
        _configure_happy_path(mock_client)
        _configure_user_recordings(
            mock_client,
            {
                "host-user": [_recording("uuid-shared")],
                "member-user": [_recording("uuid-shared")],
            },
        )

        docs = self._documents(connector)

        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-shared",
            "ZOOM_MEETING_uuid-shared",
        ]

    def test_a_mechanism_that_finds_nothing_does_not_stall_the_others(self) -> None:
        connector, mock_client = _make_connector(
            meeting_ids=[], host_emails=["host@example.com"], group_id="group-1"
        )
        _configure_happy_path(mock_client)
        _configure_user_recordings(
            mock_client, {"member-user": [_recording("uuid-member")]}
        )

        docs = self._documents(connector)

        assert [d.id for d in docs] == ["ZOOM_MEETING_uuid-member"]

    def test_a_run_resumes_mid_group_from_a_serialized_checkpoint(self) -> None:
        # Two members, so the first step ends inside the group rather than
        # finishing it: only then does the checkpoint carry a host cursor.
        connector, mock_client = _make_connector(meeting_ids=[], group_id="group-1")
        _configure_happy_path(mock_client)
        _configure_user_recordings(
            mock_client,
            {
                "member-one": [_recording("uuid-standup")],
                "member-two": [_recording("uuid-retro")],
            },
            members=[
                user(id="member-one", email="one@example.com"),
                user(id="member-two", email="two@example.com"),
            ],
        )

        checkpoint = connector.build_dummy_checkpoint()
        generator = connector.load_from_checkpoint(
            _POLL_START, _FULL_HISTORY_END, checkpoint
        )
        try:
            while True:
                next(generator)
        except StopIteration as stop:
            checkpoint = stop.value

        # The guarantee being resumed: the cursor names the host it stopped on,
        # so a member leaving cannot shift a later one under it.
        assert checkpoint.recordings.source_cursor == {"host_id": "member-two"}

        restored = connector.validate_checkpoint_json(checkpoint.model_dump_json())
        outputs = load_everything_from_checkpoint_connector_from_checkpoint(
            connector, _POLL_START, _FULL_HISTORY_END, restored
        )
        docs = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        # The second member is the one the cursor names, so it is the one a
        # broken resume would skip.
        assert [d.id for d in docs] == [
            "ZOOM_MEETING_uuid-standup",
            "ZOOM_MEETING_uuid-retro",
        ]
        assert outputs[-1].next_checkpoint.has_more is False


def _run_with_perm_sync(
    connector: ZoomConnector,
) -> list[Document | ConnectorFailure]:
    """The shared helper only drives load_from_checkpoint, so the permission
    sync entry point needs its own loop. It carries the shared helper's iteration
    guard too: a connector that stops clearing has_more would otherwise hang the
    suite rather than fail it."""
    checkpoint = connector.build_dummy_checkpoint()
    items: list[Document | ConnectorFailure] = []
    iterations = 0
    while checkpoint.has_more:
        iterations += 1
        if iterations > _ITERATION_LIMIT:
            raise RuntimeError("Too many iterations. Infinite loop?")
        generator = CheckpointOutputWrapper[ZoomConnectorCheckpoint]()(
            connector.load_from_checkpoint_with_perm_sync(
                _POLL_START, _FULL_HISTORY_END, checkpoint
            )
        )
        for document, _hierarchy, failure, next_checkpoint in generator:
            if document is not None:
                items.append(document)
            if failure is not None:
                items.append(failure)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint
    return items


class TestPermissionSyncEntryPoint:
    """Onyx calls load_from_checkpoint_with_perm_sync only for a connector set
    to SYNC access, and load_from_checkpoint for every other one. The two must
    not behave the same, or a connector that cannot use an access list still
    pays two to three extra Zoom calls for every document."""

    def _access_configured(self, mock_client: MagicMock) -> None:
        _configure_happy_path(mock_client)
        mock_client.list_past_meeting_participants.return_value = [
            participant(user_email="attended@example.com"),
            participant(user_email=""),
        ]
        mock_client.list_meeting_registrants.return_value = [
            registrant(email="approved@example.com", status="approved"),
            registrant(email="cancelled@example.com", status="denied"),
        ]
        mock_client.list_meeting_invitees.return_value = [
            invitee(email="invited@example.com")
        ]

    def test_perm_sync_run_populates_the_access_list(self) -> None:
        connector, mock_client = _make_connector()
        self._access_configured(mock_client)

        documents = [
            d for d in _run_with_perm_sync(connector) if isinstance(d, Document)
        ]

        assert len(documents) == 1
        access = documents[0].external_access
        assert access is not None
        assert access.external_user_emails == {
            "attended@example.com",
            "approved@example.com",
            "invited@example.com",
        }
        assert access.external_user_group_ids == set()
        assert access.is_public is False

    def test_a_normal_run_leaves_the_access_list_alone(self) -> None:
        connector, mock_client = _make_connector()
        self._access_configured(mock_client)

        outputs = load_everything_from_checkpoint_connector(
            connector, _POLL_START, _FULL_HISTORY_END
        )
        documents = [
            item
            for output in outputs
            for item in output.items
            if isinstance(item, Document)
        ]

        assert len(documents) == 1
        assert documents[0].external_access is None
        mock_client.list_past_meeting_participants.assert_not_called()
        mock_client.list_meeting_registrants.assert_not_called()
        mock_client.list_meeting_invitees.assert_not_called()

    def test_an_access_list_failure_becomes_a_document_failure(self) -> None:
        """A document indexed with the wrong access is worse than one a targeted
        reindex can come back for."""
        connector, mock_client = _make_connector()
        _configure_happy_path(mock_client)
        response = requests.Response()
        response.status_code = 400
        response._content = b'{"code": 300, "message": "unexpected"}'
        mock_client.list_past_meeting_participants.side_effect = requests.HTTPError(
            "boom", response=response
        )

        items = _run_with_perm_sync(connector)

        assert [type(item) for item in items] == [ConnectorFailure]
        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert "access list" in failure.failure_message
