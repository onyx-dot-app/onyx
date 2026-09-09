from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.zoom.client import ZoomClient, ZoomNotEntitledError
from onyx.connectors.zoom.models import (
    ZoomInvitee,
    ZoomPanelist,
    ZoomParticipant,
    ZoomRegistrant,
)
from onyx.connectors.zoom.recordings.access import (
    permanently_unavailable,
    zoom_access_resolver,
)
from onyx.connectors.zoom.recordings.models import OccurrenceWork, ZoomSessionType
from onyx.connectors.zoom.recordings.session_types import get_session_type_handler
from tests.unit.onyx.connectors.zoom.zoom_api_shapes import (
    invitee,
    panelist,
    participant,
    registrant,
)


def _work(session_type: ZoomSessionType = ZoomSessionType.MEETING) -> OccurrenceWork:
    return OccurrenceWork(
        session_type=session_type,
        session_id="111",
        occurrence_uuid="uuid-abc",
    )


def _client(
    participants: list[ZoomParticipant] | None = None,
    registrants: list[ZoomRegistrant] | None = None,
    invitees: list[ZoomInvitee] | None = None,
    panelists: list[ZoomPanelist] | None = None,
) -> MagicMock:
    client = MagicMock(spec=ZoomClient)
    client.list_past_meeting_participants.return_value = participants or []
    client.list_past_webinar_participants.return_value = participants or []
    client.list_meeting_registrants.return_value = registrants or []
    client.list_webinar_registrants.return_value = registrants or []
    client.list_meeting_invitees.return_value = invitees or []
    client.list_webinar_panelists.return_value = panelists or []
    return client


def _resolve(client: MagicMock, work: OccurrenceWork) -> set[str] | None:
    access = zoom_access_resolver(
        client, work, get_session_type_handler(work.session_type)
    )
    return access.external_user_emails if access else None


def _http_error(status: int, code: int | str | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    if code is not None:
        response._content = f'{{"code": {code!r}, "message": "nope"}}'.replace(
            "'", '"'
        ).encode()
    else:
        response._content = b"not json"
    return requests.HTTPError("boom", response=response)


class TestAccessListSources:
    """Each source can be present or absent independently, so the union has to
    hold up with any combination of them missing."""

    def test_participants_only(self) -> None:
        client = _client(participants=[participant(user_email="a@example.com")])

        assert _resolve(client, _work()) == {"a@example.com"}

    def test_registrants_only(self) -> None:
        client = _client(
            registrants=[registrant(email="b@example.com", status="approved")]
        )

        assert _resolve(client, _work()) == {"b@example.com"}

    def test_invitees_only(self) -> None:
        client = _client(invitees=[invitee(email="c@example.com")])

        assert _resolve(client, _work()) == {"c@example.com"}

    def test_all_sources_are_unioned(self) -> None:
        client = _client(
            participants=[participant(user_email="a@example.com")],
            registrants=[registrant(email="b@example.com", status="approved")],
            invitees=[invitee(email="c@example.com")],
        )

        assert _resolve(client, _work()) == {
            "a@example.com",
            "b@example.com",
            "c@example.com",
        }

    def test_the_same_person_in_two_sources_appears_once(self) -> None:
        client = _client(
            participants=[participant(user_email="same@example.com")],
            registrants=[registrant(email="same@example.com", status="approved")],
        )

        assert _resolve(client, _work()) == {"same@example.com"}

    def test_addresses_are_lower_cased_to_one_spelling(self) -> None:
        client = _client(
            participants=[participant(user_email="Jane@Example.com")],
            registrants=[registrant(email="jane@example.com", status="approved")],
        )

        assert _resolve(client, _work()) == {"jane@example.com"}

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        client = _client(participants=[participant(user_email="  a@example.com  ")])

        assert _resolve(client, _work()) == {"a@example.com"}


class TestCancelledRegistrations:
    """Zoom has no cancelled state: cancelling a registration sets the status to
    denied, so filtering to approved is what excludes it."""

    def test_a_cancelled_registrant_is_excluded(self) -> None:
        client = _client(
            registrants=[
                registrant(email="approved@example.com", status="approved"),
                registrant(email="cancelled@example.com", status="denied"),
                registrant(email="waiting@example.com", status="pending"),
            ]
        )

        assert _resolve(client, _work()) == {"approved@example.com"}

    def test_the_status_query_parameter_is_not_trusted_alone(self) -> None:
        """The handler asks Zoom for approved registrants and checks the record
        again, so a denied one is still excluded if Zoom ignores the filter."""
        client = _client(
            registrants=[registrant(email="denied@example.com", status="denied")]
        )

        assert _resolve(client, _work()) is None


class TestExternalInvitees:
    def test_an_external_invitee_still_gets_access(self) -> None:
        """Being invited is what grants access, wherever the person works."""
        client = _client(
            invitees=[
                invitee(email="colleague@example.com", internal_user=True),
                invitee(email="outsider@vendor.com", internal_user=False),
            ]
        )

        assert _resolve(client, _work()) == {
            "colleague@example.com",
            "outsider@vendor.com",
        }


class TestBlankEmails:
    """Zoom returns an empty email for anyone outside the host's account, and a
    person with no email cannot be granted access."""

    def test_blank_emails_are_dropped(self) -> None:
        client = _client(
            participants=[
                participant(user_email="real@example.com"),
                participant(user_email=""),
                participant(user_email="   "),
            ]
        )

        assert _resolve(client, _work()) == {"real@example.com"}

    def test_all_blank_emails_fall_back_instead_of_hiding_the_document(self) -> None:
        client = _client(participants=[participant(user_email="")])

        # None means no access list, so document-set and group access applies.
        # An empty access list would hide the document from everyone.
        assert _resolve(client, _work()) is None


class TestWebinarSources:
    def test_panelists_are_included(self) -> None:
        """A panelist presents without necessarily registering, so without this
        a speaker is missing from the webinar they spoke at."""
        client = _client(panelists=[panelist(email="speaker@example.com")])

        assert _resolve(client, _work(ZoomSessionType.WEBINAR)) == {
            "speaker@example.com"
        }

    def test_webinars_never_ask_for_invitees(self) -> None:
        """Zoom has no invitee list on a webinar; asking would 404 every time."""
        client = _client(participants=[participant(user_email="a@example.com")])

        _resolve(client, _work(ZoomSessionType.WEBINAR))

        client.list_meeting_invitees.assert_not_called()

    def test_meetings_never_ask_for_panelists(self) -> None:
        client = _client(participants=[participant(user_email="a@example.com")])

        _resolve(client, _work())

        client.list_webinar_panelists.assert_not_called()


class TestGroupsAreNeverAnAccessPrincipal:
    def test_external_user_group_ids_is_always_empty(self) -> None:
        """Zoom cannot grant a session to a Group. A Group only ever scopes
        Discovery, and meeting_invitees holds single emails with no group entry
        type, so there is nothing this could ever be filled from."""
        client = _client(
            participants=[participant(user_email="a@example.com")],
            registrants=[registrant(email="b@example.com", status="approved")],
            invitees=[invitee(email="c@example.com")],
        )

        access = zoom_access_resolver(
            client, _work(), get_session_type_handler(ZoomSessionType.MEETING)
        )

        assert access is not None
        assert access.external_user_group_ids == set()
        assert access.is_public is False


class TestPermanentVersusTransientFailures:
    """Retrying a permanent denial can never work, so it means the source has no
    data. A transient failure has to reach the caller and become a document
    failure a targeted reindex can retry."""

    @pytest.mark.parametrize(
        "error",
        [
            _http_error(400, 12702),  # meeting is past its retention window
            _http_error(404, 3001),  # session was deleted
            _http_error(404),  # not found without a body
            _http_error(400, 200),  # account plan does not allow it
        ],
    )
    def test_permanent_denials_are_treated_as_no_data(
        self, error: requests.HTTPError
    ) -> None:
        assert permanently_unavailable(error) is True

        client = _client(
            registrants=[registrant(email="b@example.com", status="approved")]
        )
        client.list_past_meeting_participants.side_effect = error

        # The other sources still answer, so the document keeps a real access list.
        assert _resolve(client, _work()) == {"b@example.com"}

    @pytest.mark.parametrize(
        "error",
        [
            _http_error(500),
            _http_error(429),
            _http_error(400, 300),  # a bad request we did not anticipate
            requests.ConnectionError("dropped"),
        ],
    )
    def test_transient_failures_propagate(self, error: Exception) -> None:
        assert permanently_unavailable(error) is False

        client = _client()
        client.list_past_meeting_participants.side_effect = error

        with pytest.raises(type(error)):
            _resolve(client, _work())

    def test_a_missing_webinar_add_on_costs_only_that_source(self) -> None:
        """Host and group discovery finds webinars through the recordings
        listing, which needs no add-on, so an account without one still indexes
        them. Failing here would take the whole run down, meetings included."""
        error = ZoomNotEntitledError("Webinar plan is missing.")
        assert permanently_unavailable(error) is True

        client = _client(
            registrants=[registrant(email="b@example.com", status="approved")]
        )
        client.list_past_webinar_participants.side_effect = error

        assert _resolve(client, _work(ZoomSessionType.WEBINAR)) == {"b@example.com"}

    def test_a_missing_scope_is_never_swallowed(self) -> None:
        """Swallowing this would empty the access list of every document on the
        account and look like a Zoom retention problem."""
        error = InsufficientPermissionsError("no meeting:read:admin")
        assert permanently_unavailable(error) is False

        client = _client()
        client.list_past_meeting_participants.side_effect = error

        with pytest.raises(InsufficientPermissionsError):
            _resolve(client, _work())

    def test_every_source_gone_falls_back(self) -> None:
        client = _client()
        client.list_past_meeting_participants.side_effect = _http_error(400, 12702)
        client.list_meeting_registrants.side_effect = _http_error(404)
        client.list_meeting_invitees.side_effect = _http_error(404)

        assert _resolve(client, _work()) is None
