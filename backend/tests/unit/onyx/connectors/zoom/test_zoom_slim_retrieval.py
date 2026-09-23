"""Tests for the Zoom slim (pruning) enumeration.

Pruning deletes every indexed document the enumeration leaves out, so each test
here asks one of two questions: does this list everything indexing wrote, and
does it raise rather than answer short.
"""

import itertools
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.models import ConnectorMissingCredentialError, SlimDocument
from onyx.connectors.zoom.connector import ZoomConnector
from onyx.connectors.zoom.models import (
    ZoomMeetingDetails,
    ZoomRecordingEntry,
    ZoomRecordingPage,
    ZoomSessionOccurrence,
    ZoomUser,
    ZoomUserPage,
)
from onyx.connectors.zoom.recordings.discovery import (
    EARLIEST_RECORDING_DATE,
    listing_windows,
)
from onyx.connectors.zoom.recordings.inventory import (
    _MAX_DOCUMENTS_PER_BATCH,
    _SCOPES_PER_HEARTBEAT,
)
from tests.unit.onyx.connectors.zoom.helpers import http_error, mock_zoom_client
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    meeting_details,
    past_meeting_details,
    recording_entry,
    user,
    webinar_details,
)

_ZOOM_CREDS = {
    "zoom_account_id": "acct",
    "zoom_client_id": "cid",
    "zoom_client_secret": "secret",
}

# The id every recording builder defaults to.
_NUMBER = "6840331990"


def _windows_per_host() -> int:
    """What one host costs the walk. Zoom's launch is the listing floor and
    today the ceiling, so the count grows by one every 30 days."""
    today = datetime.now(timezone.utc).date()
    return len(listing_windows(EARLIEST_RECORDING_DATE, today))


def _connector(**kwargs: Any) -> tuple[ZoomConnector, MagicMock]:
    connector = ZoomConnector(**kwargs)
    connector.load_credentials(_ZOOM_CREDS)
    client = mock_zoom_client()
    connector.client = client
    return connector, client


def _listing_by_host(
    pages: dict[str, ZoomRecordingPage],
) -> Any:
    """A recordings listing that answers per host, and says no such user for
    anyone it was not given."""

    def answer(user_id: str, **_: Any) -> ZoomRecordingPage:
        if user_id not in pages:
            raise http_error(404, 1001)
        return pages[user_id]

    return answer


def _recording(uuid: str, **overrides: Any) -> ZoomRecordingEntry:
    return recording_entry(uuid=uuid, **overrides)


def _recording_page(*recordings: ZoomRecordingEntry) -> ZoomRecordingPage:
    # A listing with no total_records is failed as one Zoom may have cut short.
    return ZoomRecordingPage(recordings=list(recordings), total_records=len(recordings))


def _user_page(*users: ZoomUser) -> ZoomUserPage:
    return ZoomUserPage(users=list(users), total_records=len(users))


def _listing(client: MagicMock, *recordings: ZoomRecordingEntry) -> None:
    client.list_user_recordings.return_value = _recording_page(*recordings)


def _documents(connector: ZoomConnector) -> list[SlimDocument]:
    return [
        item
        for batch in connector.retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    ]


def _ids(connector: ZoomConnector) -> set[str]:
    return {document.id for document in _documents(connector)}


def _windows(client: MagicMock) -> list[dict[str, Any]]:
    """The listing calls that were windows of the walk. The one-day probe that
    checks a host exists before the walk is not one."""
    return [
        call.kwargs
        for call in client.list_user_recordings.call_args_list
        if "from_date" in call.kwargs
        and call.kwargs["from_date"] != call.kwargs.get("to_date")
    ]


def _walked(client: MagicMock) -> list[str]:
    return [window["user_id"] for window in _windows(client)]


class TestPruningUsesTheSlimPath:
    def test_pruning_never_drives_the_checkpoint_crawl(self) -> None:
        connector, client = _connector(host_emails=["jill@example.com"])
        _listing(client, _recording("uuid-1"))

        with patch.object(connector, "load_from_checkpoint") as crawl:
            result = extract_ids_from_runnable_connector(connector)

        crawl.assert_not_called()
        client.get_recording.assert_not_called()
        assert "ZOOM_MEETING_uuid-1" in result.raw_id_to_parent

    def test_slim_retrieval_without_credentials_raises(self) -> None:
        connector = ZoomConnector(meeting_ids=["111"])
        with pytest.raises(ConnectorMissingCredentialError):
            connector.retrieve_all_slim_docs()

    @pytest.mark.parametrize(
        "blank_config",
        [
            {"meeting_ids": []},
            {
                "host_emails": ["jill@example.com"],
                "include_meetings": False,
                "include_webinars": False,
            },
        ],
    )
    def test_a_connector_with_nothing_in_scope_refuses_to_enumerate(
        self, blank_config: dict[str, Any]
    ) -> None:
        # A blank config never reaches validate_connector_settings on this path,
        # and enumerating nothing deletes everything.
        connector, _ = _connector(**blank_config)

        with pytest.raises(ConnectorValidationError):
            connector.retrieve_all_slim_docs()


class TestTheWalkIgnoresThePollWindow:
    @pytest.mark.parametrize(
        "start_time",
        [
            # The bug this feature exists for. The meeting-id crawl cannot see
            # past Zoom's 15-month instances cap, so pruning deleted these.
            "2016-02-01T10:00:00Z",
            # Discovery drops a recording dated after the poll window so a poll
            # does not download it twice. The same trim here would delete the
            # newest documents in the index.
            "2099-01-01T10:00:00Z",
        ],
    )
    def test_a_recording_outside_any_poll_window_is_still_enumerated(
        self, start_time: str
    ) -> None:
        connector, client = _connector(host_emails=["jill@example.com"])
        _listing(client, _recording("uuid-1", start_time=start_time))

        found = _ids(connector)

        assert found == {"ZOOM_MEETING_uuid-1"}
        assert min(window["from_date"] for window in _windows(client)) == date(
            2013, 1, 1
        )

    def test_every_host_gets_its_newest_window_again_after_the_whole_walk(
        self,
    ) -> None:
        # Re-asking per host would run a minute into a half-hour walk, so the
        # catch-up pass has to come after every host.
        connector, client = _connector(group_id="group-1")
        # Distinct emails, or the walk merges them into one host.
        client.list_group_members.return_value = _user_page(
            user(id="u1", email="u1@example.com"), user(id="u2", email="u2@example.com")
        )
        _listing(client)

        list(connector.retrieve_all_slim_docs())

        assert _walked(client)[-2:] == ["u1", "u2"]
        assert _walked(client).count("u1") == _windows_per_host() + 1

    def test_a_start_time_we_cannot_read_costs_the_column_not_the_prune(self) -> None:
        connector, client = _connector(host_emails=["jill@example.com"])
        _listing(client, _recording("uuid-1", start_time="the other tuesday"))

        documents = _documents(connector)

        assert {document.id for document in documents} == {"ZOOM_MEETING_uuid-1"}
        assert all(document.doc_created_at is None for document in documents)


class TestSlimFailuresNeverDeleteAnything:
    @pytest.mark.parametrize(
        "error",
        [
            http_error(500),  # Zoom is broken
            http_error(429),  # throttled past the client's own retries
            http_error(400, 12702),  # too old to describe, not proof of absence
            http_error(404, 3301),  # "no recording", which is not "no such user"
            http_error(404),  # a 404 with no code at all, such as from a proxy
            InsufficientPermissionsError("the scope was revoked"),
        ],
    )
    def test_a_listing_that_fails_raises_rather_than_answering_short(
        self, error: Exception
    ) -> None:
        connector, client = _connector(host_emails=["jill@example.com"])
        client.list_user_recordings.side_effect = error

        with pytest.raises(type(error)):
            list(connector.retrieve_all_slim_docs())

    def test_a_host_zoom_has_no_record_of_goes_without_taking_the_others(
        self,
    ) -> None:
        # Asking Zoom about the email itself is what makes this a 404. Matching
        # it inside a paged user listing gives silence instead, which cannot be
        # told apart from a page that came back short.
        connector, client = _connector(
            host_emails=["gone@example.com", "jill@example.com"]
        )
        client.list_user_recordings.side_effect = _listing_by_host(
            {"jill@example.com": _recording_page(_recording("uuid-1"))}
        )

        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}
        # Asked about once, then left out of the walk.
        asked = [
            call.kwargs["user_id"]
            for call in client.list_user_recordings.call_args_list
        ]
        assert asked.count("gone@example.com") == 1
        assert "gone@example.com" not in _walked(client)

    def test_a_credential_that_recognises_nobody_stops_the_prune(self) -> None:
        # Zoom answers the same 1001 for a deleted user and for one in another
        # account, so a credential pointed elsewhere would delete everything.
        connector, client = _connector(host_emails=["jill@example.com"])
        client.list_user_recordings.side_effect = _listing_by_host({})

        with pytest.raises(ConnectorValidationError, match="recognised none"):
            list(connector.retrieve_all_slim_docs())

    @pytest.mark.parametrize(
        "error",
        [
            InsufficientPermissionsError("missing group:read:admin"),
            # Indexing reports this one and carries on with no hosts. Doing the
            # same here would enumerate nothing and delete the whole Group.
            http_error(400),
        ],
    )
    def test_a_group_zoom_will_not_list_stops_the_prune(self, error: Exception) -> None:
        connector, client = _connector(group_id="group-1")
        client.list_group_members.side_effect = error

        with pytest.raises(type(error)):
            list(connector.retrieve_all_slim_docs())

    def test_a_group_member_zoom_just_named_but_cannot_list_raises(self) -> None:
        # A 404 on an id Zoom handed us in the same breath is not absence.
        connector, client = _connector(group_id="group-1")
        client.list_group_members.return_value = _user_page(user(id="u1"))
        client.list_user_recordings.side_effect = http_error(404, 1001)

        with pytest.raises(requests.HTTPError):
            list(connector.retrieve_all_slim_docs())


class TestSessionTypeComesFromTheConfiguredField:
    @pytest.mark.parametrize(
        ("config", "recording_type", "expected"),
        [
            # Indexing writes one document per field, so enumerating one of
            # them would delete the other on every prune.
            pytest.param(
                {"meeting_ids": [_NUMBER], "webinar_ids": [_NUMBER]},
                "2",
                {"ZOOM_MEETING_uuid-1", "ZOOM_WEBINAR_uuid-1"},
                id="a number in both id fields yields both documents",
            ),
            # Zoom's meeting and webinar numbers look identical, so the field
            # the admin chose is the only thing both paths can agree on.
            pytest.param(
                {"meeting_ids": [_NUMBER]},
                "6",
                {"ZOOM_MEETING_uuid-1"},
                id="a number in the wrong field keeps the id indexing wrote",
            ),
            # Raising would block all pruning for the connector forever, and an
            # id the index never held costs nothing.
            pytest.param(
                {"host_emails": ["jill@example.com"]},
                "4242",
                {"ZOOM_MEETING_uuid-1", "ZOOM_WEBINAR_uuid-1"},
                id="a type code zoom added later goes under every type in scope",
            ),
            pytest.param(
                {"host_emails": ["jill@example.com"]},
                "99",
                set(),
                id="a portal upload is skipped",
            ),
            # Documented sharp edge: narrowing the configuration prunes.
            pytest.param(
                {"host_emails": ["jill@example.com"], "include_webinars": False},
                "6",
                set(),
                id="unticking webinars leaves them out",
            ),
        ],
    )
    def test_which_documents_a_recording_stands_for(
        self, config: dict[str, Any], recording_type: str, expected: set[str]
    ) -> None:
        connector, client = _connector(**config)
        recording = _recording("uuid-1", type=recording_type)
        client.get_recording.return_value = recording
        _listing(client, recording)

        assert _ids(connector) == expected


class TestTheIdAllowlistFindsItsHost:
    @staticmethod
    def _nothing_answers(client: MagicMock) -> None:
        client.get_recording.side_effect = http_error(404, 3301)
        client.get_meeting_details.side_effect = http_error(404)
        # Code 12702 means Zoom will not say. Treating it as fatal would wedge
        # pruning for good on any account with a recording retention policy.
        client.get_past_meeting_details.side_effect = http_error(400, 12702)
        client.list_past_meeting_occurrences.return_value = []

    def test_the_recordings_endpoint_names_the_host_in_one_call(self) -> None:
        connector, client = _connector(meeting_ids=[_NUMBER])
        client.get_recording.return_value = _recording("uuid-1")
        _listing(client, _recording("uuid-1"), _recording("uuid-other", id=999))

        # The host's other meetings stay out: only the listed number is in scope.
        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}
        client.get_meeting_details.assert_not_called()
        client.get_past_meeting_details.assert_not_called()

    def test_the_scheduled_meeting_can_name_the_host(self) -> None:
        connector, client = _connector(meeting_ids=[_NUMBER])
        self._nothing_answers(client)
        client.get_meeting_details.side_effect = None
        client.get_meeting_details.return_value = meeting_details(host_id="u1")
        _listing(client, _recording("uuid-1"))

        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}

    def test_the_past_meeting_can_name_the_host(self) -> None:
        connector, client = _connector(meeting_ids=[_NUMBER])
        self._nothing_answers(client)
        client.get_past_meeting_details.side_effect = None
        client.get_past_meeting_details.return_value = past_meeting_details(
            host_id="u1"
        )
        _listing(client, _recording("uuid-1"))

        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}

    def test_any_past_run_that_still_has_a_recording_can_name_the_host(
        self,
    ) -> None:
        # Only the oldest run was recorded. Giving up after the newest few
        # would call the series unknown and prune its documents.
        connector, client = _connector(meeting_ids=[_NUMBER])
        self._nothing_answers(client)
        client.list_past_meeting_occurrences.return_value = [
            ZoomSessionOccurrence(
                uuid=f"uuid-{n}", start_time=f"2025-0{n}-01T10:00:00Z"
            )
            for n in range(1, 6)
        ]

        def recording_for(identifier: str) -> ZoomRecordingEntry:
            if identifier == "uuid-1":
                return _recording("uuid-1", host_id="u1")
            raise http_error(404, 3301)

        client.get_recording.side_effect = recording_for
        _listing(client, _recording("uuid-1"))

        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}

    def test_a_number_zoom_has_no_record_of_anywhere_loses_its_documents(
        self,
    ) -> None:
        # Only while something else proves the credential still sees the
        # account: on its own an unrecognised number stops the prune instead.
        connector, client = _connector(meeting_ids=[_NUMBER, "222"])
        self._nothing_answers(client)

        def recording_for(number: str) -> ZoomRecordingEntry:
            if number == "222":
                return _recording("uuid-2", id=222, host_id="u1")
            raise http_error(404, 3301)

        client.get_recording.side_effect = recording_for
        _listing(client, _recording("uuid-2", id=222))

        assert _ids(connector) == {"ZOOM_MEETING_uuid-2"}

    def test_a_connector_whose_numbers_zoom_all_disowns_stops_the_prune(
        self,
    ) -> None:
        # Zoom answers the same not-found for a deleted session and a foreign
        # one, so this is where a rotated credential would wipe the connector.
        connector, client = _connector(meeting_ids=[_NUMBER])
        self._nothing_answers(client)

        with pytest.raises(ConnectorValidationError, match="recognised none"):
            list(connector.retrieve_all_slim_docs())

    def test_a_server_error_while_finding_the_host_raises(self) -> None:
        connector, client = _connector(meeting_ids=[_NUMBER])
        client.get_recording.side_effect = http_error(500)

        with pytest.raises(requests.HTTPError):
            list(connector.retrieve_all_slim_docs())

    def test_a_webinar_number_never_asks_the_meeting_endpoints(self) -> None:
        connector, client = _connector(meeting_ids=[], webinar_ids=[_NUMBER])
        client.get_recording.side_effect = http_error(404, 3301)
        client.get_webinar_details.return_value = webinar_details(host_id="u1")
        _listing(client, _recording("uuid-1", type="6"))

        list(connector.retrieve_all_slim_docs())

        client.get_meeting_details.assert_not_called()
        client.get_past_meeting_details.assert_not_called()

    @pytest.mark.parametrize(
        "listing",
        [
            # The listing can leave out a recording Zoom still holds, such as
            # one recorded on-premise.
            _recording_page(),
            # Zoom no longer has the host it named. Raising would block the
            # prune for the whole connector until somebody edited the config.
            http_error(404, 1001),
        ],
    )
    def test_a_recording_zoom_proved_is_kept_whatever_the_listing_says(
        self, listing: ZoomRecordingPage | Exception
    ) -> None:
        connector, client = _connector(meeting_ids=[_NUMBER])
        client.get_recording.return_value = _recording("uuid-proven")
        client.list_user_recordings.side_effect = itertools.repeat(listing)

        assert _ids(connector) == {"ZOOM_MEETING_uuid-proven"}


class TestOneHostIsListedOnce:
    def test_a_host_two_mechanisms_name_is_walked_once_with_both_scopes(self) -> None:
        connector, client = _connector(
            meeting_ids=[_NUMBER], group_id="group-1", include_meetings=False
        )
        client.get_recording.return_value = _recording("uuid-1", host_id="u1")
        client.list_group_members.return_value = _user_page(user(id="u1"))
        _listing(
            client,
            _recording("uuid-1"),
            _recording("uuid-webinar", id=999, type="6"),
        )

        # The id list keeps its own number whatever the checkboxes say. The
        # Group keeps webinars only, because meetings were unticked.
        assert _ids(connector) == {"ZOOM_MEETING_uuid-1", "ZOOM_WEBINAR_uuid-webinar"}
        # One walk and one trailing pass, however many mechanisms name the host.
        assert _walked(client).count("u1") == _windows_per_host() + 1

    def test_a_host_named_by_email_and_by_group_is_walked_once(self) -> None:
        # The host list knows the person by email and the Group by Zoom's id,
        # and the member entry is the only thing that carries both.
        connector, client = _connector(
            host_emails=["jill@example.com"], group_id="group-1"
        )
        client.list_group_members.return_value = _user_page(
            user(id="u1", email="Jill@Example.com")
        )
        _listing(client, _recording("uuid-1"))

        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}
        assert _walked(client).count("u1") == _windows_per_host() + 1
        assert "jill@example.com" not in _walked(client)


class TestBatchingKeepsThePruneAlive:
    def test_a_host_with_nothing_still_yields_a_batch(self) -> None:
        # The caller reacquires its Redis lock on every batch it receives, and
        # it passes no callback, so batches are the only heartbeat.
        connector, client = _connector(host_emails=["jill@example.com"])
        _listing(client)

        batches = list(connector.retrieve_all_slim_docs())

        assert batches
        assert all(batch == [] for batch in batches)

    def test_resolving_many_numbers_yields_before_any_host_is_walked(self) -> None:
        # Each number costs several calls, and a long list would otherwise
        # outlast the lock before the first host produced a batch.
        numbers = [str(n) for n in range(1000, 1000 + _SCOPES_PER_HEARTBEAT)]
        connector, client = _connector(meeting_ids=numbers)
        for lookup in (
            client.get_recording,
            client.get_past_meeting_details,
            client.list_past_meeting_occurrences,
        ):
            lookup.side_effect = http_error(404, 3001)
        # One number has to be recognised, or the prune stops instead of walking.

        def details_for(number: str) -> ZoomMeetingDetails:
            if number == numbers[-1]:
                return meeting_details(host_id="u1")
            raise http_error(404)

        client.get_meeting_details.side_effect = details_for
        _listing(client)

        batches = connector.retrieve_all_slim_docs()

        assert next(batches) == []
        assert _walked(client) == []
        list(batches)
        assert _walked(client)

    def test_a_host_with_many_recordings_is_split_into_batches(self) -> None:
        connector, client = _connector(host_emails=["jill@example.com"])
        _listing(
            client,
            *[_recording(f"uuid-{n}") for n in range(_MAX_DOCUMENTS_PER_BATCH + 10)],
        )

        batches = list(connector.retrieve_all_slim_docs())

        assert len(batches) > 1
        assert all(len(batch) <= _MAX_DOCUMENTS_PER_BATCH for batch in batches[:-1])
