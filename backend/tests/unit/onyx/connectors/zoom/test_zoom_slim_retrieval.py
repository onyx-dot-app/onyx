"""Tests for the Zoom slim (pruning) enumeration.

Pruning deletes every indexed document the enumeration leaves out, so each test
here asks one of two questions: does this list everything indexing wrote, and
does it raise rather than answer short.
"""

import itertools
from datetime import date
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
from onyx.connectors.zoom.client import ZoomNotEntitledError
from onyx.connectors.zoom.connector import ZoomConnector
from onyx.connectors.zoom.models import (
    ZoomRecordingEntry,
    ZoomRecordingPage,
    ZoomSessionOccurrence,
    ZoomUserPage,
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

# Zoom's launch is the listing floor, so this is what one host costs.
_WINDOWS_PER_HOST = 173
# The id every recording builder defaults to.
_NUMBER = "6840331990"


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


def _listing(client: MagicMock, *recordings: ZoomRecordingEntry) -> None:
    client.list_user_recordings.return_value = ZoomRecordingPage(
        recordings=list(recordings)
    )


def _documents(connector: ZoomConnector) -> list[SlimDocument]:
    return [
        item
        for batch in connector.retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    ]


def _ids(connector: ZoomConnector) -> set[str]:
    return {document.id for document in _documents(connector)}


def _walked(client: MagicMock) -> list[str]:
    return [
        call.kwargs["user_id"]
        for call in client.list_user_recordings.call_args_list
        if "from_date" in call.kwargs
    ]


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
        asked_from = [
            call.kwargs["from_date"]
            for call in client.list_user_recordings.call_args_list
        ]

        assert found == {"ZOOM_MEETING_uuid-1"}
        assert min(asked_from) == date(2013, 1, 1)

    def test_every_host_gets_its_newest_window_again_after_the_whole_walk(
        self,
    ) -> None:
        # Re-asking per host would run a minute into a half-hour walk, so the
        # catch-up pass has to come after every host.
        connector, client = _connector(group_id="group-1")
        client.list_group_members.return_value = ZoomUserPage(
            users=[user(id="u1"), user(id="u2")]
        )
        _listing(client)

        list(connector.retrieve_all_slim_docs())

        assert _walked(client)[-2:] == ["u1", "u2"]
        assert _walked(client).count("u1") == _WINDOWS_PER_HOST + 1

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
            ZoomNotEntitledError("the webinar add-on is gone"),
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
            {"jill@example.com": ZoomRecordingPage(recordings=[_recording("uuid-1")])}
        )

        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}
        # Asked about once, then left out of the 173-window walk.
        assert _walked(client).count("gone@example.com") == 1

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
        client.list_group_members.return_value = ZoomUserPage(users=[user(id="u1")])
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
    def test_the_recordings_endpoint_names_the_host_in_one_call(self) -> None:
        connector, client = _connector(meeting_ids=[_NUMBER])
        client.get_recording.return_value = _recording("uuid-1")
        _listing(client, _recording("uuid-1"), _recording("uuid-other", id=999))

        # The host's other meetings stay out: only the listed number is in scope.
        assert _ids(connector) == {"ZOOM_MEETING_uuid-1"}
        client.get_meeting_details.assert_not_called()
        client.get_past_meeting_details.assert_not_called()

    @pytest.mark.parametrize(
        ("answers_at", "expected"),
        [
            ("scheduled", {"ZOOM_MEETING_uuid-1"}),
            ("past", {"ZOOM_MEETING_uuid-1"}),
            ("instances", {"ZOOM_MEETING_uuid-1"}),
            # Zoom has no record of the number anywhere, so its documents go.
            ("nowhere", set()),
        ],
    )
    def test_each_fallback_in_turn_can_name_the_host(
        self, answers_at: str, expected: set[str]
    ) -> None:
        connector, client = _connector(meeting_ids=[_NUMBER])
        client.get_recording.side_effect = http_error(404, 3301)
        client.get_meeting_details.side_effect = http_error(404)
        # Code 12702 means Zoom will not say. Treating it as fatal would wedge
        # pruning for good on any account with a recording retention policy.
        client.get_past_meeting_details.side_effect = http_error(400, 12702)
        client.list_past_meeting_occurrences.return_value = []

        if answers_at == "scheduled":
            client.get_meeting_details.side_effect = None
            client.get_meeting_details.return_value = meeting_details(host_id="u1")
        elif answers_at == "past":
            client.get_past_meeting_details.side_effect = None
            client.get_past_meeting_details.return_value = past_meeting_details(
                host_id="u1"
            )
        elif answers_at == "instances":
            client.list_past_meeting_occurrences.return_value = [
                ZoomSessionOccurrence(uuid="uuid-1", start_time="2020-01-01T10:00:00Z")
            ]
            client.get_recording.side_effect = [
                http_error(404, 3301),
                _recording("uuid-1"),
            ]
        _listing(client, _recording("uuid-1"))

        assert _ids(connector) == expected

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
            ZoomRecordingPage(),
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
        client.list_group_members.return_value = ZoomUserPage(users=[user(id="u1")])
        _listing(
            client,
            _recording("uuid-1"),
            _recording("uuid-webinar", id=999, type="6"),
        )

        # The id list keeps its own number whatever the checkboxes say. The
        # Group keeps webinars only, because meetings were unticked.
        assert _ids(connector) == {"ZOOM_MEETING_uuid-1", "ZOOM_WEBINAR_uuid-webinar"}
        # One probe for the id list's host, then one walk and one trailing pass.
        assert _walked(client).count("u1") == _WINDOWS_PER_HOST + 2


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
            client.get_meeting_details,
            client.get_past_meeting_details,
            client.list_past_meeting_occurrences,
        ):
            lookup.side_effect = http_error(404, 3001)

        assert list(connector.retrieve_all_slim_docs()) == [[]]

    def test_a_host_with_many_recordings_is_split_into_batches(self) -> None:
        connector, client = _connector(host_emails=["jill@example.com"])
        _listing(
            client,
            *[_recording(f"uuid-{n}") for n in range(_MAX_DOCUMENTS_PER_BATCH + 10)],
        )

        batches = list(connector.retrieve_all_slim_docs())

        assert len(batches) > 1
        assert all(len(batch) <= _MAX_DOCUMENTS_PER_BATCH for batch in batches[:-1])
