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
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    InputType,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.connector import (
    ZoomConnector,
    ZoomConnectorCheckpoint,
    parse_session_types,
    parse_treat_link_access_as_public,
)
from onyx.connectors.zoom.models import (
    ZoomRecordingEntry,
    ZoomRecordingPage,
    ZoomSessionOccurrence,
    ZoomUser,
    ZoomUserPage,
)
from onyx.connectors.zoom.rate_limit import (
    DEFAULT_RATE_LIMIT_SHARE,
    ZoomPlanTier,
    ZoomRateLimitSettings,
)
from onyx.connectors.zoom.recordings.discovery import ALL_SESSION_TYPES
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    RecordingsState,
    ZoomSessionType,
)
from onyx.db.enums import AccessType
from onyx.db.models import User
from onyx.server.documents import connector as connector_router
from onyx.server.documents.connector import create_connector_from_model
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
from tests.unit.onyx.connectors.zoom.helpers import (
    SAMPLE_VTT,
    http_error,
    mock_zoom_client,
    with_recording_access,
    with_transcript,
)
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    occurrence,
    past_meeting_details,
    recording_entry,
    recording_registrant,
    recording_settings,
    recording_with_transcript,
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
    include_meetings: bool | None = None,
    include_webinars: bool | None = None,
    treat_link_access_as_public: bool | None = None,
) -> tuple[ZoomConnector, MagicMock]:
    # Don't write `meeting_ids or [...]` here: it swaps a caller's empty list
    # for the default, and the empty-allowlist tests below then pass for the
    # wrong reason.
    connector = ZoomConnector(
        meeting_ids=["111"] if meeting_ids is None else meeting_ids,
        webinar_ids=webinar_ids,
        host_emails=host_emails,
        group_id=group_id,
        include_meetings=include_meetings,
        include_webinars=include_webinars,
        treat_link_access_as_public=treat_link_access_as_public,
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
    mock_client.get_recording.side_effect = lambda uuid: recording_with_transcript(
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
    mock_client.get_recording.side_effect = lambda uuid: recording_with_transcript(
        download_url=f"https://zoom.example/{uuid}.vtt"
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


class TestAConnectorWithNoIndexingStartRunsFromTheEpoch:
    """run_docfetching falls back to an epoch start when no indexing start date
    is set, so load_from_checkpoint has to survive one. Pruning no longer comes
    through here -- see test_zoom_slim_retrieval.py -- but indexing still does.
    """

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


class TestIndexingStartAtConfigTime:
    """These drive the endpoints an admin posts to rather than any check itself,
    so an endpoint that quietly stops forwarding the date is still caught.
    """

    _START = datetime(2026, 1, 1, tzinfo=timezone.utc)

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

    def test_zoom_creates_without_a_start_date(self) -> None:
        """Zoom used to be refused here. The crawl now floors itself at Zoom's
        launch instead, so a missing date costs calls rather than the connector."""
        with self._rows_written() as written:
            self._post(create_connector_from_model)

        assert [row.indexing_start for row in written] == [None]

    # Only the plain endpoint: the mock-credential one carries on into credential
    # creation and a Celery dispatch that a stubbed session cannot answer for.
    def test_the_start_date_an_admin_sets_is_the_one_stored(self) -> None:
        """Demanding a date buys nothing if the endpoint then drops it, which is
        exactly what the update path did."""
        with self._rows_written() as written:
            self._post(create_connector_from_model, indexing_start=self._START)

        assert [row.indexing_start for row in written] == [self._START]

    def test_another_source_also_creates_without_one(self) -> None:
        with self._rows_written() as written:
            self._post(create_connector_from_model, source=DocumentSource.CONFLUENCE)

        assert [row.indexing_start for row in written] == [None]


def _with_client(**config: Any) -> tuple[ZoomConnector, MagicMock]:
    connector = ZoomConnector(**config)
    client = mock_zoom_client()
    connector.client = client
    return connector, client


class TestZoomConnectorValidateSettings:
    def test_no_discovery_mechanism_rejected(self) -> None:
        connector = ZoomConnector(meeting_ids=[])
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    def test_configured_meeting_ids_accepted(self) -> None:
        connector, _ = _with_client(meeting_ids=["111"])
        connector.validate_connector_settings()

    def test_webinar_ids_alone_are_a_discovery_mechanism(self) -> None:
        connector, _ = _with_client(webinar_ids=["222"])
        connector.validate_connector_settings()

    def test_host_emails_alone_are_a_discovery_mechanism(self) -> None:
        connector, _ = _with_client(host_emails=["host@example.com"])
        connector.validate_connector_settings()

    def test_a_group_alone_is_a_discovery_mechanism(self) -> None:
        connector, _ = _with_client(group_id="group-1")
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

    def test_connectors_saved_before_the_checkboxes_keep_both_types(self) -> None:
        assert parse_session_types(None, None) == ALL_SESSION_TYPES

    def test_each_checkbox_drops_only_its_own_type(self) -> None:
        assert parse_session_types(True, False) == {ZoomSessionType.MEETING}
        assert parse_session_types(False, True) == {ZoomSessionType.WEBINAR}

    @pytest.mark.parametrize("value", ["true", 1, ["meetings"]])
    def test_a_checkbox_value_that_is_not_a_boolean_is_rejected(
        self, value: Any
    ) -> None:
        with pytest.raises(ValueError):
            parse_session_types(value, True)

    def test_connectors_saved_before_the_link_access_box_have_it_on(self) -> None:
        # Off leaves nearly every transcript readable by its owner alone.
        assert parse_treat_link_access_as_public(None) is True
        assert parse_treat_link_access_as_public(False) is False

    @pytest.mark.parametrize("value", ["true", 1, ["on"]])
    def test_a_link_access_value_that_is_not_a_boolean_is_rejected(
        self, value: Any
    ) -> None:
        with pytest.raises(ValueError, match="true or false"):
            parse_treat_link_access_as_public(value)

    def test_a_host_with_both_types_unticked_is_rejected_at_setup(self) -> None:
        connector = ZoomConnector(
            host_emails=["host@example.com"],
            include_meetings=False,
            include_webinars=False,
        )
        with pytest.raises(ConnectorValidationError) as exc:
            connector.validate_connector_settings()

        assert "meetings, webinars, or both" in str(exc.value)

    def test_id_lists_do_not_need_a_type_ticked(self) -> None:
        # An ID list already says which type each ID is.
        connector, _ = _with_client(
            meeting_ids=["111"], include_meetings=False, include_webinars=False
        )
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

    def test_validation_without_credentials_is_refused(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        with pytest.raises(ConnectorMissingCredentialError):
            connector.validate_connector_settings()

    def test_a_blank_form_is_rejected_before_zoom_is_called(self) -> None:
        connector, client = _with_client(meeting_ids=[])
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()
        client.check_credentials.assert_not_called()

    def test_a_wrong_secret_is_rejected_at_setup(self) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.check_credentials.side_effect = CredentialInvalidError("refused")

        with pytest.raises(CredentialInvalidError):
            connector.validate_connector_settings()

        client.list_past_meeting_occurrences.assert_not_called()

    def test_a_missing_scope_is_rejected_at_setup(self) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.side_effect = InsufficientPermissionsError(
            "Zoom denied access (pastMeetings)"
        )

        with pytest.raises(InsufficientPermissionsError) as exc:
            connector.validate_connector_settings()

        assert "pastMeetings" in str(exc.value)

    def test_an_id_pasted_with_spaces_is_probed_without_them(self) -> None:
        connector, client = _with_client(webinar_ids=["857 9609 3688"])
        client.list_past_webinar_occurrences.return_value = []

        connector.validate_connector_settings()

        client.list_past_webinar_occurrences.assert_called_once_with("85796093688")

    def test_a_malformed_meeting_id_is_rejected_at_setup(self) -> None:
        # Zoom answers a non-numeric id with a 400, not a 404.
        connector, client = _with_client(meeting_ids=["not-a-meeting"])
        client.list_past_meeting_occurrences.side_effect = http_error(400, 300)

        with pytest.raises(ConnectorValidationError) as exc:
            connector.validate_connector_settings()

        assert "not-a-meeting" in str(exc.value)

    def test_a_missing_directory_scope_is_rejected_at_setup(self) -> None:
        connector, client = _with_client(host_emails=["host@example.com"])
        client.list_users.side_effect = InsufficientPermissionsError(
            "Zoom denied the account's users: does not contain scopes"
        )

        with pytest.raises(InsufficientPermissionsError):
            connector.validate_connector_settings()

    def test_the_recordings_scope_is_probed_with_a_directory_user(self) -> None:
        connector, client = _with_client(host_emails=["host@example.com"])
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_user_recordings.return_value = ZoomRecordingPage(
            recordings=[recording_entry(uuid="rec-1")]
        )

        connector.validate_connector_settings()

        client.list_user_recordings.assert_called_once()
        assert client.list_user_recordings.call_args.args[0] == "u1"

    def test_an_empty_latest_window_looks_back_before_giving_up(self) -> None:
        # A quiet host has nothing in the last 30 days, and an empty sample
        # would leave every recording scope unprobed.
        connector, client = _with_client(host_emails=["host@example.com"])
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_user_recordings.side_effect = [
            ZoomRecordingPage(recordings=[]),
            ZoomRecordingPage(recordings=[]),
            ZoomRecordingPage(recordings=[recording_entry(uuid="rec-old")]),
        ]

        connector.validate_connector_settings()

        windows = [call.args[1:] for call in client.list_user_recordings.call_args_list]
        assert len(windows) == 3
        assert all(end - start == timedelta(days=30) for start, end in windows)
        assert [w[1] for w in windows] == [windows[0][1], windows[0][0], windows[1][0]]
        client.get_recording.assert_called_once_with("rec-old")

    def test_a_later_occurrence_is_tried_when_the_first_was_not_recorded(
        self,
    ) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.return_value = [
            occurrence(uuid="occ-1"),
            occurrence(uuid="occ-2"),
        ]
        client.get_recording.side_effect = [
            http_error(404, 3301),
            recording_entry(uuid="occ-2", host_id="u1"),
        ]

        connector.validate_connector_settings()

        assert [c.args[0] for c in client.get_recording.call_args_list] == [
            "occ-1",
            "occ-2",
        ]

    def test_sampling_stops_after_a_few_unrecorded_occurrences(self) -> None:
        # Each try is a call, and a long series of unrecorded runs must not
        # turn validation into a crawl.
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.return_value = [
            occurrence(uuid=f"occ-{n}") for n in range(8)
        ]
        client.get_recording.side_effect = http_error(404, 3301)

        connector.validate_connector_settings()

        assert client.get_recording.call_count == 5

    def test_the_recordings_scope_is_probed_with_a_group_member(self) -> None:
        connector, client = _with_client(group_id="group-1")
        client.list_group_members.return_value = ZoomUserPage(
            users=[user(id="member-1")]
        )

        connector.validate_connector_settings()

        assert client.list_user_recordings.call_args.args[0] == "member-1"

    def test_the_recordings_scope_is_not_probed_for_id_scoping(self) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.return_value = []

        connector.validate_connector_settings()

        client.list_user_recordings.assert_not_called()
        client.get_recording.assert_not_called()

    def test_the_transcript_scope_is_probed_on_the_first_occurrence(self) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.return_value = [
            occurrence(uuid="occ-1"),
            occurrence(uuid="occ-2"),
        ]

        connector.validate_connector_settings()

        client.get_recording.assert_called_once_with("occ-1")

    def test_the_transcript_scope_is_probed_on_the_first_recording(self) -> None:
        connector, client = _with_client(host_emails=["host@example.com"])
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_user_recordings.return_value = ZoomRecordingPage(
            recordings=[recording_entry(uuid="rec-1")]
        )

        connector.validate_connector_settings()

        client.get_recording.assert_called_once_with("rec-1")

    def test_a_recorded_session_is_preferred_over_a_bare_occurrence(self) -> None:
        # An occurrence may have no recording, and then the transcript endpoint
        # answers 404 and never reveals whether the scope is granted. A
        # recordings listing only returns sessions that have one.
        connector, client = _with_client(
            meeting_ids=["111"], host_emails=["host@example.com"]
        )
        client.list_past_meeting_occurrences.return_value = [occurrence(uuid="occ-1")]
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_user_recordings.return_value = ZoomRecordingPage(
            recordings=[recording_entry(uuid="rec-1")]
        )

        connector.validate_connector_settings()

        client.get_recording.assert_called_once_with("rec-1")

    def test_the_recording_sample_asks_for_zooms_widest_window(self) -> None:
        # A single day is usually empty, and an empty sample leaves the
        # transcript scope unprobed.
        connector, client = _with_client(host_emails=["host@example.com"])
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_user_recordings.return_value = ZoomRecordingPage()

        connector.validate_connector_settings()

        _, start, end = client.list_user_recordings.call_args.args
        assert (end - start).days == 30

    def test_a_sample_session_without_a_recording_still_passes(self) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.return_value = [occurrence()]
        client.get_recording.side_effect = http_error(404)

        connector.validate_connector_settings()

    def test_a_missing_recording_scope_is_rejected_at_setup(self) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.return_value = [occurrence()]
        client.get_recording.side_effect = InsufficientPermissionsError(
            "does not contain scopes:[cloud_recording:read:list_recording_files:admin]"
        )

        with pytest.raises(InsufficientPermissionsError):
            connector.validate_connector_settings()

    def test_an_unknown_meeting_id_does_not_pause_the_connector(self) -> None:
        # validate_connector_settings runs before every indexing attempt and a
        # ConnectorValidationError pauses the cc_pair, so one meeting that Zoom
        # has deleted must not stop the other mechanisms from crawling.
        # Discovery reports it as an indexing error instead.
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.side_effect = http_error(404, 3001)

        connector.validate_connector_settings()

    @pytest.mark.parametrize("code", [12702, 3001], ids=["too-old", "not-found"])
    def test_a_gone_meeting_reported_under_a_400_does_not_pause_either(
        self, code: int
    ) -> None:
        # Zoom says a session is gone with a 404 on some endpoints and with its
        # own code under a 400 on others. A meeting ages past a year on its own,
        # so this one arrives without anyone touching the connector.
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.side_effect = http_error(400, code)

        connector.validate_connector_settings()

    def test_the_webinar_add_on_is_probed_even_when_a_meeting_gave_a_sample(
        self,
    ) -> None:
        connector, client = _with_client(meeting_ids=["111"], webinar_ids=["222"])
        client.list_past_meeting_occurrences.return_value = [occurrence(uuid="occ-1")]

        connector.validate_connector_settings()

        client.list_past_webinar_occurrences.assert_called_once_with("222")

    def test_an_unknown_group_does_not_pause_the_connector(self) -> None:
        connector, client = _with_client(group_id="group-1")
        client.list_group_members.side_effect = http_error(404)

        connector.validate_connector_settings()

    @pytest.mark.parametrize(
        "failure",
        [http_error(503), http_error(429), requests.ConnectionError("down")],
    )
    def test_a_zoom_outage_at_setup_is_not_read_as_bad_settings(
        self, failure: Exception
    ) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.side_effect = failure

        with pytest.raises(UnexpectedValidationError):
            connector.validate_connector_settings()

    def test_each_configured_mechanism_is_probed_once_on_its_first_value(
        self,
    ) -> None:
        connector, client = _with_client(
            meeting_ids=["111", "112"],
            webinar_ids=["222", "223"],
            host_emails=["a@example.com", "b@example.com"],
            group_id="group-1",
        )
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_group_members.return_value = ZoomUserPage(
            users=[user(id="member-1")]
        )
        client.list_user_recordings.return_value = ZoomRecordingPage(
            recordings=[recording_entry(uuid="rec-1")]
        )

        connector.validate_connector_settings()

        client.check_credentials.assert_called_once()
        client.list_past_meeting_occurrences.assert_called_once()
        assert client.list_past_meeting_occurrences.call_args.args[0] == "111"
        client.list_past_webinar_occurrences.assert_called_once_with("222")
        client.list_users.assert_called_once()
        client.list_group_members.assert_called_once_with("group-1")
        client.list_user_recordings.assert_called_once()

    def test_only_configured_mechanisms_are_probed(self) -> None:
        connector, client = _with_client(meeting_ids=["111"], host_emails=["  "])

        connector.validate_connector_settings()

        client.list_past_webinar_occurrences.assert_not_called()
        client.list_users.assert_not_called()
        client.list_group_members.assert_not_called()


class TestZoomConnectorProbeRecordingAccessPermissions:
    """The permission-sync probe. It runs after validate_connector_settings,
    on the recording that one sampled."""

    def _validated(self, validate: bool = True) -> tuple[ZoomConnector, MagicMock]:
        connector, client = _with_client(host_emails=["host@example.com"])
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_user_recordings.return_value = ZoomRecordingPage(
            recordings=[recording_entry(uuid="rec-1", host_id="u1")]
        )
        client.get_recording.return_value = recording_entry(uuid="rec-1", host_id="u1")
        if validate:
            connector.validate_connector_settings()
        return connector, client

    def test_every_permission_sync_scope_is_probed_on_the_sampled_recording(
        self,
    ) -> None:
        connector, client = self._validated()

        connector.probe_recording_access_permissions()

        client.get_recording_settings.assert_called_once_with("rec-1")
        # One registrant is enough to see the scope.
        client.list_recording_registrants.assert_called_once_with(
            "rec-1", status="approved", limit=1
        )
        client.get_user.assert_called_once_with("u1")
        client.get_recording_authentication_rules.assert_called_once_with("u1")

    @pytest.mark.parametrize(
        "refused",
        [
            lambda client: client.get_recording_settings,
            lambda client: client.list_recording_registrants,
            lambda client: client.get_user,
            lambda client: client.get_recording_authentication_rules,
        ],
        ids=["settings", "registrants", "user", "rules"],
    )
    def test_a_missing_scope_is_rejected_at_setup(
        self, refused: Callable[[MagicMock], MagicMock]
    ) -> None:
        connector, client = self._validated()
        refused(client).side_effect = InsufficientPermissionsError(
            "does not contain scopes:[cloud_recording:read:recording_settings:admin]"
        )

        with pytest.raises(InsufficientPermissionsError):
            connector.probe_recording_access_permissions()

    def test_it_samples_on_its_own_when_settings_were_not_validated_first(
        self,
    ) -> None:
        connector, client = self._validated(validate=False)

        connector.probe_recording_access_permissions()

        client.get_recording_settings.assert_called_once_with("rec-1")

    def test_without_a_recording_only_the_rules_scope_can_be_probed(self) -> None:
        # Zoom checks some endpoints for the resource before the scope, so a
        # 404 on a made-up recording would hide whether the scope is granted.
        # The rules need only a user, and validation already found one.
        connector, client = _with_client(host_emails=["host@example.com"])
        client.list_users.return_value = ZoomUserPage(users=[user(id="u1")])
        client.list_user_recordings.return_value = ZoomRecordingPage(recordings=[])
        connector.validate_connector_settings()

        connector.probe_recording_access_permissions()

        client.get_recording_settings.assert_not_called()
        client.list_recording_registrants.assert_not_called()
        client.get_recording_authentication_rules.assert_called_once_with("u1")
        # And it does not go looking for a sample a second time.
        client.list_users.assert_called_once()

    def test_an_id_only_connector_with_no_recording_finds_a_user_for_the_rules(
        self,
    ) -> None:
        connector, client = _with_client(meeting_ids=["111"])
        client.list_past_meeting_occurrences.return_value = []
        client.list_users.return_value = ZoomUserPage(users=[user(id="u9")])
        connector.validate_connector_settings()

        connector.probe_recording_access_permissions()

        client.get_recording_authentication_rules.assert_called_once_with("u9")

    def test_a_sampled_recording_zoom_has_since_deleted_does_not_pause(
        self,
    ) -> None:
        connector, client = self._validated()
        client.get_recording_settings.side_effect = http_error(404)

        connector.probe_recording_access_permissions()

    def test_without_credentials_it_raises(self) -> None:
        connector = ZoomConnector(host_emails=["host@example.com"])

        with pytest.raises(ConnectorMissingCredentialError):
            connector.probe_recording_access_permissions()


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
        mock_client.get_recording.assert_called_once_with("uuid-111")
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

        def _recording(uuid: str) -> ZoomRecordingEntry:
            if uuid == "uuid-2":
                raise RuntimeError("boom")
            return recording_with_transcript(
                download_url=f"https://zoom.example/{uuid}.vtt"
            )

        mock_client.get_recording.side_effect = _recording

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
        mock_client.get_recording.assert_not_called()
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
        mock_client.get_recording.side_effect = requests.HTTPError(
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
        mock_client.get_recording.side_effect = requests.HTTPError(
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
        mock_client.get_recording.side_effect = requests.HTTPError(
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
        mock_client.get_recording.assert_called_once_with("uuid-222")
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
    group = (
        [user(id="member-user", email="member@example.com")]
        if members is None
        else members
    )
    mock_client.list_group_members.return_value = ZoomUserPage(
        users=group, total_records=len(group)
    )

    def recordings(user_id: str, **_: object) -> ZoomRecordingPage:
        found = recordings_by_user.get(user_id, [])
        return ZoomRecordingPage(recordings=found, total_records=len(found))

    mock_client.list_user_recordings.side_effect = recordings


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

    def test_unticking_webinars_leaves_a_hosts_webinars_out(self) -> None:
        connector, mock_client = _make_connector(
            meeting_ids=[], host_emails=["host@example.com"], include_webinars=False
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

        assert [d.id for d in docs] == ["ZOOM_MEETING_uuid-town-hall"]

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
        with_transcript(mock_client, host_id="owner-1")
        with_recording_access(
            mock_client,
            settings=recording_settings(on_demand=True),
            registrants=[
                recording_registrant(email="viewer@example.com", status="approved")
            ],
        )

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
            "owner@example.com",
            "viewer@example.com",
        }
        assert access.external_user_group_ids == set()
        assert access.is_public is True

    def test_the_box_off_leaves_link_access_out(self) -> None:
        connector, mock_client = _make_connector(treat_link_access_as_public=False)
        self._access_configured(mock_client)

        documents = [
            d for d in _run_with_perm_sync(connector) if isinstance(d, Document)
        ]

        access = documents[0].external_access
        assert access is not None
        assert access.is_public is False

    def test_the_catalogue_and_each_owner_are_asked_for_once_per_run(self) -> None:
        connector, mock_client = _make_connector(meeting_ids=["111"])
        self._access_configured(mock_client)
        mock_client.list_past_meeting_occurrences.side_effect = None
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomSessionOccurrence(uuid="uuid-1", start_time=_days_ago(21)),
            ZoomSessionOccurrence(uuid="uuid-2", start_time=_days_ago(14)),
            ZoomSessionOccurrence(uuid="uuid-3", start_time=_days_ago(7)),
        ]

        documents = [
            d for d in _run_with_perm_sync(connector) if isinstance(d, Document)
        ]

        assert len(documents) == 3
        assert mock_client.get_recording_settings.call_count == 3
        mock_client.get_user.assert_called_once_with("owner-1")
        mock_client.list_users.assert_called_once()
        mock_client.get_recording_authentication_rules.assert_called_once()

    def test_the_catalogue_is_not_asked_for_unless_a_recording_names_a_rule(
        self,
    ) -> None:
        connector, mock_client = _make_connector()
        _configure_happy_path(mock_client)
        with_transcript(mock_client, host_id="owner-1")
        with_recording_access(
            mock_client,
            settings=recording_settings(
                recording_authentication=False, authentication_option=""
            ),
        )

        documents = [
            d for d in _run_with_perm_sync(connector) if isinstance(d, Document)
        ]

        assert documents[0].external_access is not None
        assert documents[0].external_access.is_public is True
        mock_client.list_users.assert_not_called()
        mock_client.get_recording_authentication_rules.assert_not_called()

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
        mock_client.get_recording_settings.assert_not_called()
        mock_client.get_user.assert_not_called()

    def test_an_access_list_failure_becomes_a_document_failure(self) -> None:
        """A document indexed with the wrong access is worse than one a targeted
        reindex can come back for."""
        connector, mock_client = _make_connector()
        _configure_happy_path(mock_client)
        response = requests.Response()
        response.status_code = 400
        response._content = b'{"code": 300, "message": "unexpected"}'
        mock_client.get_recording_settings.side_effect = requests.HTTPError(
            "boom", response=response
        )

        items = _run_with_perm_sync(connector)

        assert [type(item) for item in items] == [ConnectorFailure]
        failure = items[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document is not None
        assert "access list" in failure.failure_message
