from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest
import requests
from pydantic import ValidationError
from requests.adapters import HTTPAdapter

from onyx.connectors.cross_connector_utils import rate_limit_wrapper
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.zoom import client as zoom_client
from onyx.connectors.zoom.client import (
    _API_BASE_URL,
    _MAX_PAGE_SIZE,
    _MAX_RATE_LIMIT_SLEEP_SECONDS,
    _MAX_RATE_LIMIT_SLEEPS,
    _OAUTH_TOKEN_URL,
    _RATE_LIMIT_PERIOD_SECONDS,
    ZoomClient,
    ZoomNotEntitledError,
    ZoomPlanTier,
    ZoomRateLimitError,
    ZoomRateLimitTier,
    _encode_meeting_identifier,
    _reject_non_zoom_download_url,
    _tier_calls_per_second,
    parse_plan_tier,
    parse_rate_limit_percent,
)
from onyx.connectors.zoom.models import ZoomTranscript
from onyx.connectors.zoom.recordings.models import fails_the_whole_run

_ZOOM_DOWNLOAD_URL = "https://zoom.us/rec/download/abc.vtt"

# Zoom's own documented example, which returns all three readiness fields at
# once even though their field docs say that cannot happen.
_DOCUMENTED_TRANSCRIPT = {
    "meeting_id": "uaFkQyFCSwya8iNYtkAw3A==",
    "account_id": "Cx3wERazSgup7ZWRHQM8-w",
    "meeting_topic": "My Personal Meeting",
    "host_id": "_0ctZtY0REqWalTmwvrdIw",
    "transcript_created_time": "2025-06-27T13:48:24Z",
    "can_download": True,
    "auto_delete": True,
    "auto_delete_date": "2052-11-07",
    "download_url": "https://zoom.example/t.vtt",
    "download_restriction_reason": "NOT_READY",
}


_DOCUMENTED_PAST_MEETING = {
    "id": 5638296721,
    "uuid": "4444AAAiAAAAAiAiAiiAii==",
    "duration": 60,
    "start_time": "2021-07-13T21:44:51Z",
    "end_time": "2021-07-13T23:00:51Z",
    "host_id": "x1yCzABCDEfg23HiJKl4mN",
    "dept": "Developers",
    "participants_count": 2,
    "source": "Zoom",
    "topic": "My Meeting",
    "total_minutes": 55,
    "type": 1,
    "user_email": "jchill@example.com",
    "user_name": "Jill Chill",
    "has_meeting_summary": False,
}


# The five configuration objects ZoomWebinarDetails deliberately leaves off.
# Naming them keeps the round-trip assertion honest about what it skips.
_WEBINAR_CONFIG_FIELDS = frozenset(
    {
        "occurrences",
        "recurrence",
        "settings",
        "simulive_delay_start",
        "tracking_fields",
    }
)

# Every field of Zoom's documented `GET /webinars/{webinarId}` example. The five
# configuration objects are trimmed to one entry each, since nothing reads inside
# them and `settings` alone holds 77 more fields.
_DOCUMENTED_WEBINAR = {
    "id": 97871060099,
    "uuid": "m3WqMkvuRXyYqH+eKWhk9w==",
    "host_id": "30R7kT7bTIKSNUFEuH_Qlg",
    "host_email": "jchill@example.com",
    "topic": "My Webinar",
    "type": 5,
    "agenda": "My webinar",
    "duration": 60,
    "start_time": "2022-03-26T06:44:14Z",
    "timezone": "America/Los_Angeles",
    "created_at": "2022-03-26T07:18:32Z",
    "creation_source": "open_api",
    "join_url": "https://example.com/j/11111",
    "start_url": "https://example.com/s/11111",
    "registration_url": "https://example.com/webinar/register/7ksAkRCoEpt1",
    "password": "123456",
    "encrypted_passcode": "8pEkRweVXPV3Ob2KJYgFTRlDtl1gSn.1",
    "h323_passcode": "123456",
    "template_id": "ull6574eur",
    "record_file_id": "f09340e1-cdc3-4eae-9a74-98f9777ed908",
    "is_simulive": True,
    "transition_to_live": False,
    "simulive_delay_start": {"enable": True, "time": 10, "timeunit": "second"},
    "occurrences": [{"occurrence_id": "1648194360000", "status": "available"}],
    "recurrence": {"type": 1, "repeat_interval": 1},
    "settings": {"approval_type": 0, "auto_recording": "cloud"},
    "tracking_fields": [{"field": "field1", "value": "value1"}],
}


_DOCUMENTED_PARTICIPANT = {
    "id": "30R7kT7bTIKSNUFEuH_Qlg",
    "name": "Jill Chill",
    "user_id": "27423744",
    "registrant_id": "_f08HhPJS82MIVLuuFaJPg",
    "user_email": "jchill@example.com",
    "join_time": "2022-03-23T06:58:09Z",
    "leave_time": "2022-03-23T07:02:28Z",
    "duration": 259,
    "failover": False,
    "status": "in_meeting",
    "internal_user": False,
}

_DOCUMENTED_REGISTRANT = {
    "id": "9tboDiHUQAeOnbmudzWa5g",
    "email": "jchill@example.com",
    "first_name": "Jill",
    "last_name": "Chill",
    "status": "approved",
    "create_time": "2022-03-22T05:59:09Z",
    "join_url": "https://example.com/j/11111",
}

_DOCUMENTED_PANELIST = {
    "id": "Tg2b6GhcQKKbV7nSCbDKug",
    "email": "jchill@example.com",
    "name": "Jill Chill",
    "join_url": "https://example.com/j/11111",
}


# The pacing test asserts which tier ran the call, not what the client parsed,
# so one body has to satisfy whichever model the endpoint builds. Pydantic drops
# fields a model does not declare, so the documented examples merge cleanly.
_ANY_SESSION_PAYLOAD = {
    **_DOCUMENTED_TRANSCRIPT,
    **_DOCUMENTED_PAST_MEETING,
    **_DOCUMENTED_WEBINAR,
}


def _transcript(**overrides: Any) -> ZoomTranscript:
    """Most fields are required, so a readiness case has to start from a whole
    response rather than the two fields it exercises.
    """
    return ZoomTranscript.model_validate({**_DOCUMENTED_TRANSCRIPT, **overrides})


def _response(
    status: int,
    payload: Any = None,
    text: str = "",
    location: str | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.is_redirect = location is not None
    response.headers = {"Location": location} if location else {}
    response.json.return_value = payload if payload is not None else {}
    response.text = text
    return response


def _client() -> ZoomClient:
    client = ZoomClient(account_id="acct", client_id="cid", client_secret="secret")
    client._access_token = "tok"
    client._token_expires_at = float("inf")
    return client


class TestEncodeMeetingIdentifier:
    def test_plain_numeric_id_is_untouched(self) -> None:
        assert _encode_meeting_identifier("81234567890") == "81234567890"

    def test_slash_is_escaped_so_it_cannot_split_the_url_path(self) -> None:
        assert "/" not in _encode_meeting_identifier("abc/def==")

    def test_uuid_starting_with_a_slash_is_encoded_twice(self) -> None:
        once = "%2FabcXYZ%3D%3D"
        assert _encode_meeting_identifier("/abcXYZ==") == "%252FabcXYZ%253D%253D"
        assert _encode_meeting_identifier("/abcXYZ==") != once

    def test_uuid_containing_a_double_slash_is_encoded_twice(self) -> None:
        assert _encode_meeting_identifier("ab//cd==") == "ab%252F%252Fcd%253D%253D"

    def test_single_interior_slash_is_encoded_once(self) -> None:
        assert _encode_meeting_identifier("ab/cd==") == "ab%2Fcd%3D%3D"


class TestAccessToken:
    def test_token_is_fetched_once_and_reused(self) -> None:
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")
        client._session = MagicMock()
        post = client._session.post
        post.return_value = _response(200, {"access_token": "t1", "expires_in": 3600})

        assert client._get_access_token() == "t1"
        assert client._get_access_token() == "t1"

        assert post.call_count == 1
        assert post.call_args.kwargs["params"] == {
            "grant_type": "account_credentials",
            "account_id": "a",
        }
        assert post.call_args.kwargs["auth"] == ("c", "s")

    def test_token_is_refreshed_before_it_expires(self) -> None:
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")
        client._session = MagicMock()
        post = client._session.post
        post.side_effect = [
            _response(200, {"access_token": "t1", "expires_in": 3600}),
            _response(200, {"access_token": "t2", "expires_in": 3600}),
        ]
        assert client._get_access_token() == "t1"

        client._token_expires_at = 0.0

        assert client._get_access_token() == "t2"
        assert post.call_count == 2

    def test_a_token_response_without_a_token_names_the_missing_field(self) -> None:
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")
        client._session = MagicMock()
        client._session.post.return_value = _response(200, {"expires_in": 3600})

        with pytest.raises(ValidationError) as exc:
            client._get_access_token()

        assert "access_token" in str(exc.value)

    def test_an_expiry_zoom_did_not_send_is_not_invented(self) -> None:
        # Inventing an expiry keeps a token Zoom ended early in use until a 401.
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")
        client._session = MagicMock()
        client._session.post.return_value = _response(200, {"access_token": "t1"})

        with pytest.raises(ValidationError):
            client._get_access_token()

    @pytest.mark.parametrize(
        "status, expected",
        [(401, CredentialInvalidError), (403, InsufficientPermissionsError)],
    )
    def test_a_refused_token_raises_a_typed_error(
        self, status: int, expected: type[Exception]
    ) -> None:
        # An untyped error here is retried forever instead of telling the admin
        # the credentials are wrong.
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")
        client._session = MagicMock()
        client._session.post.return_value = _response(status)

        with pytest.raises(expected):
            client._get_access_token()


class TestStaleTokenIsRetried:
    """Delete the retry and a stale token starts reporting itself as a bad
    credential, which eventually marks the connector invalid."""

    def test_stale_token_is_refreshed_and_the_request_succeeds(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.post.return_value = _response(
            200, {"access_token": "fresh", "expires_in": 3600}
        )
        client._session.request.side_effect = [_response(401), _response(200, {})]

        response = client._request("GET", "/anything")

        assert response.status_code == 200
        assert client._session.request.call_count == 2
        # The retry must carry the new token, not the rejected one.
        assert (
            client._session.request.call_args.kwargs["headers"]["Authorization"]
            == "Bearer fresh"
        )

    def test_a_second_rejection_is_reported_as_expired(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.post.return_value = _response(
            200, {"access_token": "fresh", "expires_in": 3600}
        )
        client._session.request.return_value = _response(401)

        with pytest.raises(CredentialExpiredError):
            client._request("GET", "/anything")

        assert client._session.request.call_count == 2

    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_transcript_download_also_retries(
        self,
        ssrf: MagicMock,  # noqa: ARG002
    ) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.get.side_effect = [
            _response(401),
            _response(200, text="WEBVTT\n"),
        ]
        client._session.post.return_value = _response(
            200, {"access_token": "fresh", "expires_in": 3600}
        )

        assert client.download_transcript_vtt(_ZOOM_DOWNLOAD_URL) == "WEBVTT\n"
        assert client._session.get.call_count == 2

    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_transcript_download_reports_a_typed_error(
        self,
        ssrf: MagicMock,  # noqa: ARG002
    ) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.get.return_value = _response(403)
        client._session.post.return_value = _response(
            200, {"access_token": "fresh", "expires_in": 3600}
        )

        with pytest.raises(InsufficientPermissionsError):
            client.download_transcript_vtt(_ZOOM_DOWNLOAD_URL)


class TestRetryPolicy:
    @pytest.mark.parametrize(
        "url",
        [_API_BASE_URL, _OAUTH_TOKEN_URL, _ZOOM_DOWNLOAD_URL],
        ids=["api", "token", "download"],
    )
    def test_every_zoom_host_retries(self, url: str) -> None:
        # Mounting per URL left the download host on the no-retry default.
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")

        adapter = client._session.get_adapter(url)
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == 5
        assert 500 in adapter.max_retries.status_forcelist

    def test_the_transport_does_not_also_retry_429(self) -> None:
        # Two layers backing off on the same 429 multiply the wait, and a spent
        # urllib3 retry raises RetryError, which carries no response to classify
        # on. Asserting on status_forcelist alone would miss it: urllib3 retries
        # a 429 that carries a Retry-After header whatever the forcelist says.
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")

        adapter = client._session.get_adapter(_API_BASE_URL)
        assert isinstance(adapter, HTTPAdapter)
        retry = adapter.max_retries
        assert 429 not in retry.status_forcelist
        assert not retry.is_retry("GET", 429, has_retry_after=True)


class TestRequestErrorMapping:
    def test_forbidden_raises_insufficient_permissions(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(403)

        with pytest.raises(InsufficientPermissionsError) as exc:
            client._request("GET", "/meetings/1/transcript")

        # The message has to name the endpoint, since the fix is a scope change.
        assert "/meetings/1/transcript" in str(exc.value)

    def test_bearer_token_is_attached(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200)

        client._request("GET", "/anything")

        headers = client._session.request.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"


class TestGetMeetingTranscript:
    def test_parses_the_response(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_TRANSCRIPT)

        transcript = client.get_meeting_transcript("111")

        assert transcript is not None
        assert transcript.download_url == "https://zoom.example/t.vtt"
        assert transcript.download_restriction_reason == "NOT_READY"

    def test_keeps_the_fields_that_save_a_second_api_call(self) -> None:
        # The topic is the only reason to call /past_meetings, and that call is
        # the one subject to Zoom's one-year limit.
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_TRANSCRIPT)

        transcript = client.get_meeting_transcript("111")

        assert transcript is not None
        assert transcript.meeting_topic == "My Personal Meeting"
        assert transcript.host_id == "_0ctZtY0REqWalTmwvrdIw"
        assert transcript.transcript_created_time == "2025-06-27T13:48:24Z"

    def test_keeps_every_documented_field(self) -> None:
        # Nothing reads account_id or the auto-delete pair yet, so without this
        # test they look like dead fields someone can safely delete.
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_TRANSCRIPT)

        transcript = client.get_meeting_transcript("111")

        assert transcript is not None
        assert transcript.model_dump() == _DOCUMENTED_TRANSCRIPT

    def test_404_is_reported_not_swallowed(self) -> None:
        # A session that was never recorded answers 404. Reading that as "skip
        # this one" is the caller's decision, so the client only reports it.
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            404, {"code": 3322, "message": "This meeting transcript does not exist."}
        )

        with pytest.raises(requests.HTTPError) as exc:
            client.get_meeting_transcript("111")

        assert "Zoom code 3322" in str(exc.value)

    def test_identifier_is_encoded_into_the_path(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_TRANSCRIPT)

        client.get_meeting_transcript("ab/cd==")

        url = client._session.request.call_args.args[1]
        assert "ab%2Fcd%3D%3D" in url
        assert "ab/cd==" not in url


class TestGetPastMeetingDetails:
    def test_parses_the_response(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_PAST_MEETING)

        details = client.get_past_meeting_details("111")

        assert details is not None
        assert details.topic == "My Meeting"
        assert details.start_time == "2021-07-13T21:44:51Z"

    def test_keeps_every_documented_field(self) -> None:
        # Nothing reads most of these yet, so without this test they look like
        # dead fields someone can safely delete.
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_PAST_MEETING)

        details = client.get_past_meeting_details("111")

        assert details is not None
        assert details.model_dump() == _DOCUMENTED_PAST_MEETING

    def test_an_undocumented_shape_fails_here_not_in_the_connector(self) -> None:
        # Zoom documents every field on this response as always sent. If that is
        # wrong, the client has to say so rather than pass a None downstream.
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200, {k: v for k, v in _DOCUMENTED_PAST_MEETING.items() if k != "dept"}
        )

        with pytest.raises(ValidationError):
            client.get_past_meeting_details("111")

    def test_404_is_reported_not_swallowed(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        with pytest.raises(requests.HTTPError):
            client.get_past_meeting_details("111")


class TestListPastMeetingOccurrences:
    def test_reads_the_meetings_key(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {
                "meetings": [
                    {"uuid": "u1", "start_time": "2026-01-01T10:00:00Z"},
                    {"uuid": "u2", "start_time": "2026-01-08T10:00:00Z"},
                ]
            },
        )

        occurrences = client.list_past_meeting_occurrences("111")

        assert [o.uuid for o in occurrences] == ["u1", "u2"]
        assert occurrences[0].start_time == "2026-01-01T10:00:00Z"

    def test_404_is_reported_not_swallowed(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        with pytest.raises(requests.HTTPError):
            client.list_past_meeting_occurrences("111")

    def test_missing_meetings_key_yields_an_empty_list(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {})

        assert client.list_past_meeting_occurrences("111") == []


class TestListGroupMembers:
    def test_reads_the_members_key(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {
                "members": [
                    {
                        "id": "u1",
                        "email": "jill@example.com",
                        "first_name": "Jill",
                        "last_name": "Chill",
                        "type": 2,
                    },
                    {
                        "id": "u2",
                        "email": "jack@example.com",
                        "first_name": "Jack",
                        "last_name": "Chill",
                        "type": 2,
                    },
                ],
                "next_page_token": "tok",
            },
        )

        page = client.list_group_members("group-1")

        assert [(u.id, u.email) for u in page.users] == [
            ("u1", "jill@example.com"),
            ("u2", "jack@example.com"),
        ]
        assert page.next_page_token == "tok"
        params = client._session.request.call_args.kwargs["params"]
        assert params == {"page_size": _MAX_PAGE_SIZE}

    def test_page_token_is_sent_on_the_next_page(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"members": []})

        client.list_group_members("group-1", page_token="tok")

        params = client._session.request.call_args.kwargs["params"]
        assert params["next_page_token"] == "tok"

    def test_an_empty_token_ends_the_listing(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200, {"members": [], "next_page_token": ""}
        )

        assert client.list_group_members("group-1").next_page_token is None

    def test_a_missing_group_raises(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            404, {"code": 4130, "message": "Group does not exist"}
        )

        with pytest.raises(requests.HTTPError, match="Group does not exist"):
            client.list_group_members("nope")

    def test_group_id_is_encoded_into_the_path(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"members": []})

        client.list_group_members("a/b")

        url = client._session.request.call_args.args[1]
        assert url == f"{_API_BASE_URL}/groups/a%2Fb/members"


class TestListUsers:
    def test_reads_the_users_key(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "host@example.com",
                        "first_name": "Jill",
                        "last_name": "Chill",
                        "type": 2,
                    }
                ],
                "next_page_token": "",
            },
        )

        page = client.list_users()

        assert [(u.id, u.email) for u in page.users] == [("u1", "host@example.com")]
        assert page.next_page_token is None
        url = client._session.request.call_args.args[1]
        assert url == f"{_API_BASE_URL}/users"


class TestListUserRecordings:
    def _page(self) -> dict[str, Any]:
        return {
            "meetings": [
                {
                    "uuid": "BOKXuumlTAGXuqwr3bLyuQ==",
                    "id": 6840331990,
                    "topic": "My Personal Meeting",
                    "start_time": "2021-03-18T05:41:36Z",
                    "type": "1",
                    "account_id": "Cx3wERazSgup7ZWRHQM8-w",
                    "host_id": "_0ctZtY0REqWalTmwvrdIw",
                    "duration": 20,
                    "total_size": 22,
                    "recording_count": 22,
                }
            ],
            "next_page_token": "tok",
        }

    def test_reads_the_meetings_key(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, self._page())

        page = client.list_user_recordings("u1", date(2026, 1, 1), date(2026, 2, 1))

        recording = page.recordings[0]
        assert recording.uuid == "BOKXuumlTAGXuqwr3bLyuQ=="
        assert recording.topic == "My Personal Meeting"
        assert recording.start_time == "2021-03-18T05:41:36Z"
        assert page.next_page_token == "tok"

    def test_the_integer_meeting_number_becomes_the_session_id(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, self._page())

        page = client.list_user_recordings("u1", date(2026, 1, 1), date(2026, 2, 1))

        assert page.recordings[0].session_id == "6840331990"

    def test_the_window_and_page_size_go_to_zoom(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"meetings": []})

        client.list_user_recordings(
            "u1", date(2026, 1, 1), date(2026, 2, 1), page_token="tok"
        )

        params = client._session.request.call_args.kwargs["params"]
        assert params == {
            "from": "2026-01-01",
            "to": "2026-02-01",
            "page_size": _MAX_PAGE_SIZE,
            "next_page_token": "tok",
        }
        url = client._session.request.call_args.args[1]
        assert url == f"{_API_BASE_URL}/users/u1/recordings"

    def test_a_missing_user_raises_rather_than_reading_as_empty(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            404, {"code": 1001, "message": "User does not exist"}
        )

        with pytest.raises(requests.HTTPError, match="User does not exist"):
            client.list_user_recordings("nope", date(2026, 1, 1), date(2026, 2, 1))

    def test_missing_meetings_key_yields_an_empty_page(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {})

        page = client.list_user_recordings("u1", date(2026, 1, 1), date(2026, 2, 1))

        assert page.recordings == []
        assert page.next_page_token is None


class TestGetWebinarDetails:
    def test_parses_the_response(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_WEBINAR)

        details = client.get_webinar_details("222")

        assert details.topic == "My Webinar"
        assert details.start_time == "2022-03-26T06:44:14Z"

    def test_keeps_every_documented_scalar_field(self) -> None:
        # Sharing one model with /past_meetings parses no webinar at all, because
        # that model requires seven fields a webinar never carries.
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, _DOCUMENTED_WEBINAR)

        details = client.get_webinar_details("222")

        # Guards the fixture too: trimming the five out of it would quietly
        # turn the comparison below into a weaker test.
        assert _WEBINAR_CONFIG_FIELDS <= set(_DOCUMENTED_WEBINAR)
        expected = {
            k: v
            for k, v in _DOCUMENTED_WEBINAR.items()
            if k not in _WEBINAR_CONFIG_FIELDS
        }
        assert details.model_dump() == expected

    def test_a_webinar_configured_with_nothing_optional_still_parses(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {
                "id": 97871060099,
                "uuid": "m3WqMkvuRXyYqH+eKWhk9w==",
                "host_id": "30R7kT7bTIKSNUFEuH_Qlg",
                "topic": "Bare Webinar",
                "type": 5,
            },
        )

        details = client.get_webinar_details("222")

        assert details.topic == "Bare Webinar"
        assert details.start_time is None

    def test_404_is_reported_not_swallowed(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        with pytest.raises(requests.HTTPError):
            client.get_webinar_details("222")


class TestListPastWebinarOccurrences:
    def test_reads_the_webinars_key(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {
                "webinars": [
                    {"uuid": "w1", "start_time": "2026-01-01T10:00:00Z"},
                    {"uuid": "w2", "start_time": "2026-01-08T10:00:00Z"},
                ]
            },
        )

        occurrences = client.list_past_webinar_occurrences("222")

        assert [o.uuid for o in occurrences] == ["w1", "w2"]
        assert occurrences[0].start_time == "2026-01-01T10:00:00Z"

    def test_calls_the_webinar_endpoint_not_the_meeting_one(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"webinars": []})

        client.list_past_webinar_occurrences("222")

        url = client._session.request.call_args.args[1]
        assert url == f"{_API_BASE_URL}/past_webinars/222/instances"

    def test_404_is_reported_not_read_as_no_occurrences(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        with pytest.raises(requests.HTTPError):
            client.list_past_webinar_occurrences("222")

    def test_missing_webinars_key_yields_an_empty_list(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {})

        assert client.list_past_webinar_occurrences("222") == []


class TestWebinarAddOnErrors:
    """A Pro account without the Webinar add-on fails every webinar call, and
    the generic scope message sends the admin to re-check scopes that are
    already correct."""

    def test_403_names_the_add_on(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(403)

        with pytest.raises(InsufficientPermissionsError) as caught:
            client.list_past_webinar_occurrences("222")

        assert "Webinar add-on" in str(caught.value)

    def test_400_with_zooms_no_permission_code_names_the_add_on(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            400, {"code": 200, "message": "No permission."}
        )

        with pytest.raises(InsufficientPermissionsError) as caught:
            client.list_past_webinar_occurrences("222")

        assert "Webinar add-on" in str(caught.value)

    def test_a_missing_plan_keeps_the_user_zoom_named(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            400,
            {
                "code": 200,
                "message": (
                    "Webinar plan is missing. You must subscribe to the webinar "
                    "plan and enable webinars for user abc123 to perform this action."
                ),
            },
        )

        with pytest.raises(InsufficientPermissionsError) as caught:
            client.get_webinar_details("222")

        assert "Webinar add-on" in str(caught.value)
        assert "abc123" in str(caught.value)

    def test_a_string_error_code_is_still_recognised(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            400, {"code": "200", "message": "No permission."}
        )

        with pytest.raises(InsufficientPermissionsError):
            client.list_past_webinar_occurrences("222")

    def test_an_unrelated_400_is_still_an_http_error(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            400, {"code": 300, "message": "Invalid webinar ID."}
        )

        with pytest.raises(requests.HTTPError):
            client.list_past_webinar_occurrences("222")


class TestDownloadTranscriptVtt:
    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_returns_body_and_authenticates(
        self,
        ssrf: MagicMock,  # noqa: ARG002
    ) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.get.return_value = _response(200, text="WEBVTT\n")

        body = client.download_transcript_vtt(_ZOOM_DOWNLOAD_URL)

        assert body == "WEBVTT\n"
        headers = client._session.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"


class TestDownloadUrlGuard:
    """Relax the host check and the account-wide bearer token goes to whatever
    host the URL names."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com/steal.vtt",
            "https://zoom.us.evil.example.com/steal.vtt",
            "http://169.254.169.254/latest/meta-data/",
            "https://notzoom.us/x.vtt",
        ],
    )
    def test_non_zoom_host_is_refused(self, url: str) -> None:
        with pytest.raises(ValueError):
            _reject_non_zoom_download_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            # Real shapes from Zoom's docs, not invented ones.
            "https://us02web.zoom.us/rec/download/3lwWGTDTAhGO9UHg",
            "https://us02web.zoom.us/rec/webhook_download/14q-E-JtEehWe",
            "https://mycompany.zoom.us/rec/download/abc.vtt",
            "https://zoom.us/rec/download/abc.vtt",
            "https://ZOOM.US/rec/download/abc.vtt",
        ],
    )
    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_zoom_hosts_are_allowed(
        self,
        ssrf: MagicMock,  # noqa: ARG002
        url: str,
    ) -> None:
        _reject_non_zoom_download_url(url)

    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_the_guard_accepts_the_host_the_client_talks_to(
        self,
        ssrf: MagicMock,  # noqa: ARG002
    ) -> None:
        # _ZOOM_HOST and _API_BASE_URL have to move together: point the client at
        # Zoom for Government without the allowlist and every download is refused.
        api_host = urlparse(_API_BASE_URL).hostname or ""

        _reject_non_zoom_download_url(f"https://{api_host}/rec/download/abc.vtt")

    def test_the_guard_runs_before_the_token_is_sent(self) -> None:
        client = _client()
        client._session = MagicMock()

        with pytest.raises(ValueError):
            client.download_transcript_vtt("https://evil.example.com/steal.vtt")

        client._session.get.assert_not_called()


class TestTranscriptReadiness:
    def test_the_documented_example_is_not_treated_as_ready(self) -> None:
        # can_download says yes while the reason says still processing.
        transcript = ZoomTranscript.model_validate(_DOCUMENTED_TRANSCRIPT)

        assert transcript.is_downloadable is False

    def test_ready_when_nothing_objects(self) -> None:
        transcript = _transcript(
            can_download=True,
            download_url=_ZOOM_DOWNLOAD_URL,
            download_restriction_reason=None,
        )

        assert transcript.is_downloadable is True

    @pytest.mark.parametrize(
        "transcript",
        [
            _transcript(
                can_download=False,
                download_url=_ZOOM_DOWNLOAD_URL,
                download_restriction_reason=None,
            ),
            _transcript(
                can_download=True,
                download_url=None,
                download_restriction_reason=None,
            ),
            _transcript(
                can_download=True,
                download_url=_ZOOM_DOWNLOAD_URL,
                download_restriction_reason="DELETED_OR_TRASHED",
            ),
        ],
        ids=["refused", "no_url", "restricted"],
    )
    def test_any_single_objection_is_enough(self, transcript: ZoomTranscript) -> None:
        assert transcript.is_downloadable is False


class TestZoomErrorMessages:
    def test_the_zoom_code_reaches_the_message(self) -> None:
        # A meeting over a year old fails with 12702, and without this the log
        # says only "400 Client Error".
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            400,
            {"code": 12702, "message": "You cannot access a meeting older than a year"},
        )

        with pytest.raises(requests.HTTPError) as exc:
            client.get_past_meeting_details("111")

        assert "12702" in str(exc.value)
        assert "older than a year" in str(exc.value)

    def test_a_body_that_is_not_json_still_raises(self) -> None:
        client = _client()
        client._session = MagicMock()
        response = _response(500)
        response.json.side_effect = ValueError("not json")
        client._session.request.return_value = response

        with pytest.raises(requests.HTTPError):
            client.list_past_meeting_occurrences("111")


class TestDownloadRedirects:
    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_a_redirect_to_a_private_address_is_refused(
        self,
        ssrf: MagicMock,  # noqa: ARG002
    ) -> None:
        # ssrf_safe_get runs unpatched here, or this stops testing SSRF at all.
        client = _client()
        client._session = MagicMock()
        client._session.get.return_value = _response(
            302, location="https://169.254.169.254/latest/meta-data/"
        )

        with pytest.raises(ValueError):
            client.download_transcript_vtt(_ZOOM_DOWNLOAD_URL)

    @patch("onyx.connectors.zoom.client.ssrf_safe_get")
    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_the_token_does_not_follow_the_redirect(
        self,
        ssrf: MagicMock,  # noqa: ARG002
        safe_get: MagicMock,
    ) -> None:
        safe_get.return_value = _response(200, text="WEBVTT\n")
        client = _client()
        client._session = MagicMock()
        client._session.get.return_value = _response(
            302, location="https://cdn.example.com/t.vtt"
        )

        client.download_transcript_vtt(_ZOOM_DOWNLOAD_URL)

        assert "Authorization" not in (safe_get.call_args.kwargs.get("headers") or {})
        assert "tok" not in str(safe_get.call_args)

    @patch("onyx.connectors.zoom.client.ssrf_safe_get")
    @patch("onyx.connectors.zoom.client.validate_outbound_http_url")
    def test_a_relative_location_resolves_against_the_download_url(
        self,
        ssrf: MagicMock,  # noqa: ARG002
        safe_get: MagicMock,
    ) -> None:
        safe_get.return_value = _response(200, text="WEBVTT\n")
        client = _client()
        client._session = MagicMock()
        client._session.get.return_value = _response(302, location="/rec/other.vtt")

        assert client.download_transcript_vtt(_ZOOM_DOWNLOAD_URL) == "WEBVTT\n"
        assert safe_get.call_args.args[0] == "https://zoom.us/rec/other.vtt"


class TestListPastMeetingParticipants:
    def test_pages_are_joined_into_one_list(self) -> None:
        """A next_page_token dies 15 minutes after Zoom issues it, so the whole
        list is paged in one call rather than resumed later."""
        client = _client()
        client._session = MagicMock()
        client._session.request.side_effect = [
            _response(
                200,
                {
                    "participants": [
                        {**_DOCUMENTED_PARTICIPANT, "user_email": "a@example.com"}
                    ],
                    "next_page_token": "page-2",
                },
            ),
            _response(
                200,
                {
                    "participants": [
                        {**_DOCUMENTED_PARTICIPANT, "user_email": "b@example.com"}
                    ],
                    "next_page_token": "",
                },
            ),
        ]

        participants = client.list_past_meeting_participants("uuid-abc")

        assert [p.user_email for p in participants] == [
            "a@example.com",
            "b@example.com",
        ]
        assert (
            client._session.request.call_args_list[1].kwargs["params"][
                "next_page_token"
            ]
            == "page-2"
        )

    def test_a_blank_email_survives_as_far_as_the_model(self) -> None:
        """Zoom empties this for anyone outside the host's account. Dropping it
        here would hide how many people were lost."""
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200, {"participants": [{**_DOCUMENTED_PARTICIPANT, "user_email": ""}]}
        )

        assert client.list_past_meeting_participants("uuid-abc")[0].user_email == ""

    def test_a_session_with_one_attendee_returns_nothing_rather_than_failing(
        self,
    ) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {})

        assert client.list_past_meeting_participants("uuid-abc") == []

    def test_a_deleted_session_reaches_the_caller_as_a_404(self) -> None:
        """An empty page means nobody attended, but a 404 means Zoom has no such
        session. access.py tells those apart, so the client must not answer both
        with an empty list."""
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404, {"code": 3001})

        with pytest.raises(requests.HTTPError):
            client.list_past_meeting_participants("uuid-abc")

    def test_the_retention_window_error_reaches_the_caller(self) -> None:
        """Zoom answers 400 with code 12702 once a meeting is out of range. The
        access layer turns that into "no data"; the client must not hide it."""
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            400, {"code": 12702, "message": "Can not access a meeting a year ago."}
        )

        with pytest.raises(requests.HTTPError) as caught:
            client.list_past_meeting_participants("uuid-abc")

        assert "12702" in str(caught.value)


class TestListRegistrants:
    def test_the_caller_chooses_which_registrants_zoom_sends(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"registrants": []})

        client.list_meeting_registrants("111", status="approved")

        params = client._session.request.call_args.kwargs["params"]
        assert params["status"] == "approved"
        assert params["page_size"] == _MAX_PAGE_SIZE

    def test_no_status_asks_zoom_for_every_registrant(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"registrants": []})

        client.list_meeting_registrants("111")

        assert "status" not in client._session.request.call_args.kwargs["params"]

    def test_the_status_is_kept_on_each_record(self) -> None:
        """access.py decides who a registration grants access to, so it needs
        the status even though Zoom was asked to filter."""
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {
                "registrants": [
                    {**_DOCUMENTED_REGISTRANT, "status": "approved"},
                    {**_DOCUMENTED_REGISTRANT, "status": "denied"},
                ]
            },
        )

        registrants = client.list_meeting_registrants("111")

        assert [r.status for r in registrants] == ["approved", "denied"]

    def test_registration_being_off_returns_nothing(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"registrants": []})

        assert client.list_meeting_registrants("111") == []


class TestListMeetingInvitees:
    def test_invitees_are_read_out_of_the_settings_block(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {
                "settings": {
                    "meeting_invitees": [
                        {"email": "a@example.com", "internal_user": True},
                        {"email": "b@example.com", "internal_user": False},
                    ]
                }
            },
        )

        invitees = client.list_meeting_invitees("111")

        assert [i.email for i in invitees] == ["a@example.com", "b@example.com"]
        assert [i.internal_user for i in invitees] == [True, False]

    def test_an_ad_hoc_meeting_has_no_invitees(self) -> None:
        """An instant meeting was never scheduled, so there is no invite list."""
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {"settings": {}})

        assert client.list_meeting_invitees("111") == []

    def test_a_deleted_meeting_reaches_the_caller_as_a_404(self) -> None:
        """Returning an empty list here would read as a meeting nobody was invited
        to. access.py decides what a meeting Zoom has forgotten means."""
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        with pytest.raises(requests.HTTPError):
            client.list_meeting_invitees("111")


class TestListWebinarPanelists:
    def test_panelists_are_returned(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200,
            {"panelists": [{**_DOCUMENTED_PANELIST, "email": "speaker@example.com"}]},
        )

        assert client.list_webinar_panelists("222")[0].email == "speaker@example.com"

    def test_a_missing_webinar_addon_raises_the_entitlement_type(self) -> None:
        """Zoom sends this as a 400, not a 403. It gets its own type so callers
        can carry on without the data, unlike a missing scope."""
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            400, {"code": 200, "message": "Webinar plan is missing."}
        )

        with pytest.raises(ZoomNotEntitledError) as caught:
            client.list_webinar_panelists("222")

        assert "Webinar add-on" in str(caught.value)

    def test_a_missing_scope_stays_a_plain_permissions_error(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(403)

        with pytest.raises(InsufficientPermissionsError) as caught:
            client.list_webinar_panelists("222")

        assert not isinstance(caught.value, ZoomNotEntitledError)


def _rate_limited(retry_after: str | None = None) -> MagicMock:
    response = _response(429)
    response.headers = {"Retry-After": retry_after} if retry_after else {}
    return response


def _client_answering(*responses: MagicMock) -> tuple[ZoomClient, MagicMock]:
    client = _client()
    session = MagicMock()
    session.request.side_effect = list(responses)
    client._session = session
    return client, session


class _FakeClock:
    """rate_limit_builder measures its window with time.monotonic and waits with
    time.sleep, so moving both together tests pacing without any real waiting."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TestRateLimitTiers:
    """Every expectation below is the Rate Limit Label on that endpoint's own
    page in Zoom's API reference."""

    @pytest.mark.parametrize(
        "call, expected_tier",
        [
            (lambda c: c.get_meeting_transcript("1"), ZoomRateLimitTier.MEDIUM),
            (lambda c: c.get_past_meeting_details("1"), ZoomRateLimitTier.LIGHT),
            (lambda c: c.list_past_meeting_occurrences("1"), ZoomRateLimitTier.MEDIUM),
            (lambda c: c.get_webinar_details("1"), ZoomRateLimitTier.LIGHT),
            (lambda c: c.list_past_webinar_occurrences("1"), ZoomRateLimitTier.LIGHT),
            (lambda c: c.list_group_members("g"), ZoomRateLimitTier.MEDIUM),
            (lambda c: c.list_users(), ZoomRateLimitTier.MEDIUM),
            (
                lambda c: c.list_user_recordings(
                    "u", date(2024, 1, 1), date(2024, 2, 1)
                ),
                ZoomRateLimitTier.MEDIUM,
            ),
            (
                lambda c: c.list_past_meeting_participants("uuid"),
                ZoomRateLimitTier.MEDIUM,
            ),
            (
                lambda c: c.list_past_webinar_participants("uuid"),
                ZoomRateLimitTier.MEDIUM,
            ),
            (lambda c: c.list_meeting_registrants("1"), ZoomRateLimitTier.MEDIUM),
            (lambda c: c.list_webinar_registrants("1"), ZoomRateLimitTier.MEDIUM),
            (lambda c: c.list_meeting_invitees("1"), ZoomRateLimitTier.LIGHT),
            (lambda c: c.list_webinar_panelists("1"), ZoomRateLimitTier.MEDIUM),
            (
                lambda c: c.download_transcript_vtt(_ZOOM_DOWNLOAD_URL),
                ZoomRateLimitTier.MEDIUM,
            ),
        ],
    )
    def test_each_endpoint_is_paced_at_its_documented_tier(
        self,
        call: Any,
        expected_tier: ZoomRateLimitTier,
    ) -> None:
        client = _client()
        client._session = MagicMock()
        used: list[ZoomRateLimitTier] = []

        def record(
            _description: str, tier: ZoomRateLimitTier, _send: Any
        ) -> requests.Response:
            used.append(tier)
            return _response(200, _ANY_SESSION_PAYLOAD)

        client._rate_limiter = MagicMock()
        client._rate_limiter.call.side_effect = record

        call(client)

        assert used == [expected_tier]

    def test_the_token_request_is_paced_too(self) -> None:
        # The one call that cannot go through _send_authorized, so it is the
        # one that silently escapes pacing if nobody checks.
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")
        client._session = MagicMock()
        client._rate_limiter = MagicMock()
        client._rate_limiter.call.return_value = _response(
            200, {"access_token": "tok", "expires_in": 3600}
        )

        client._fetch_access_token()

        assert client._rate_limiter.call.call_count == 1

    def test_the_budget_never_reaches_zero(self) -> None:
        assert (
            _tier_calls_per_second(ZoomPlanTier.PRO, ZoomRateLimitTier.MEDIUM, 0.001)
            == 1
        )


class TestRateLimitBackoff:
    @pytest.fixture(autouse=True)
    def _instant_pacing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # These tests spend more than one second of budget. Pacing is not what
        # they are checking, and a real wait would be the slowest thing in the
        # unit suite.
        monkeypatch.setattr(rate_limit_wrapper, "time", _FakeClock())

    def test_a_429_waits_as_long_as_zoom_asks(self) -> None:
        client, _ = _client_answering(_rate_limited("3"), _response(200, {"users": []}))

        with patch("onyx.connectors.zoom.client.time.sleep") as sleep:
            page = client.list_users()

        assert [c.args[0] for c in sleep.call_args_list] == [3.0]
        assert page.users == []

    def test_a_429_without_a_retry_after_backs_off_exponentially(self) -> None:
        client, _ = _client_answering(
            _rate_limited(), _rate_limited(), _response(200, {"users": []})
        )

        with patch("onyx.connectors.zoom.client.time.sleep") as sleep:
            client.list_users()

        assert [c.args[0] for c in sleep.call_args_list] == [2.0, 4.0]

    def test_an_absurd_retry_after_is_capped(self) -> None:
        client, _ = _client_answering(
            _rate_limited("86400"), _response(200, {"users": []})
        )

        with patch("onyx.connectors.zoom.client.time.sleep") as sleep:
            client.list_users()

        assert [c.args[0] for c in sleep.call_args_list] == [
            _MAX_RATE_LIMIT_SLEEP_SECONDS
        ]

    def test_sustained_throttling_gives_up_and_fails_the_whole_run(self) -> None:
        client, session = _client_answering(
            *[_rate_limited() for _ in range(_MAX_RATE_LIMIT_SLEEPS + 1)]
        )

        with patch("onyx.connectors.zoom.client.time.sleep"):
            with pytest.raises(ZoomRateLimitError) as exc:
                client.list_users()

        assert session.request.call_count == _MAX_RATE_LIMIT_SLEEPS + 1
        assert fails_the_whole_run(exc.value)

    def test_an_exhausted_transport_retry_also_fails_the_whole_run(self) -> None:
        # urllib3 still retries 5xx, and a spent Retry raises RetryError, which
        # is not an HTTPError and so carries no status code to classify on.
        assert fails_the_whole_run(requests.exceptions.RetryError("gave up"))


class TestPacing:
    def test_a_call_over_the_budget_waits_for_the_window_to_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = _FakeClock()
        monkeypatch.setattr(rate_limit_wrapper, "time", clock)
        # One call per second makes the wait unmistakable.
        monkeypatch.setattr(zoom_client, "_DEFAULT_RATE_LIMIT_SHARE", 1.0)
        monkeypatch.setattr(
            zoom_client,
            "_PLAN_CALLS_PER_SECOND",
            {plan: {tier: 1 for tier in ZoomRateLimitTier} for plan in ZoomPlanTier},
        )

        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200)

        client._request("GET", "/first")
        started = clock.now
        client._request("GET", "/second")

        assert clock.now - started >= _RATE_LIMIT_PERIOD_SECONDS

    def test_the_tiers_are_paced_separately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Zoom gives each label its own allowance, so a light call must not be
        # held up by the medium calls a backfill is already making.
        clock = _FakeClock()
        monkeypatch.setattr(rate_limit_wrapper, "time", clock)
        monkeypatch.setattr(zoom_client, "_DEFAULT_RATE_LIMIT_SHARE", 1.0)
        monkeypatch.setattr(
            zoom_client,
            "_PLAN_CALLS_PER_SECOND",
            {plan: {tier: 1 for tier in ZoomRateLimitTier} for plan in ZoomPlanTier},
        )

        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200)

        client._request("GET", "/medium")
        started = clock.now
        client._request("GET", "/light", tier=ZoomRateLimitTier.LIGHT)

        assert clock.now == started


class TestPlanTier:
    @pytest.mark.parametrize(
        "configured, expected",
        [
            (None, ZoomPlanTier.PRO),
            ("", ZoomPlanTier.PRO),
            ("   ", ZoomPlanTier.PRO),
            ("pro", ZoomPlanTier.PRO),
            ("business_plus", ZoomPlanTier.BUSINESS_PLUS),
            ("  Business_Plus  ", ZoomPlanTier.BUSINESS_PLUS),
        ],
    )
    def test_a_plan_is_parsed_leniently_and_blank_means_pro(
        self, configured: str | None, expected: ZoomPlanTier
    ) -> None:
        assert parse_plan_tier(configured) == expected

    def test_an_unknown_plan_is_rejected_and_names_the_valid_ones(self) -> None:
        with pytest.raises(ValueError) as exc:
            parse_plan_tier("enterprise")

        assert "business_plus" in str(exc.value)

    @pytest.mark.parametrize(
        "tier", [ZoomRateLimitTier.LIGHT, ZoomRateLimitTier.MEDIUM]
    )
    def test_business_plus_gets_a_bigger_budget_than_pro(
        self, tier: ZoomRateLimitTier
    ) -> None:
        assert _tier_calls_per_second(
            ZoomPlanTier.BUSINESS_PLUS, tier, 0.25
        ) > _tier_calls_per_second(ZoomPlanTier.PRO, tier, 0.25)

    @pytest.mark.parametrize(
        "plan, expect_a_wait",
        [(ZoomPlanTier.PRO, True), (ZoomPlanTier.BUSINESS_PLUS, False)],
        ids=["pro waits", "business does not"],
    )
    def test_the_configured_plan_reaches_the_pacer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        plan: ZoomPlanTier,
        expect_a_wait: bool,
    ) -> None:
        clock = _FakeClock()
        monkeypatch.setattr(rate_limit_wrapper, "time", clock)
        monkeypatch.setattr(zoom_client, "_DEFAULT_RATE_LIMIT_SHARE", 1.0)
        monkeypatch.setattr(
            zoom_client,
            "_PLAN_CALLS_PER_SECOND",
            {
                ZoomPlanTier.PRO: {tier: 1 for tier in ZoomRateLimitTier},
                ZoomPlanTier.BUSINESS_PLUS: {tier: 2 for tier in ZoomRateLimitTier},
            },
        )

        client = ZoomClient(
            account_id="a", client_id="c", client_secret="s", plan_tier=plan
        )
        client._access_token = "tok"
        client._token_expires_at = float("inf")
        client._session = MagicMock()
        client._session.request.return_value = _response(200)

        client._request("GET", "/first")
        started = clock.now
        client._request("GET", "/second")

        assert (clock.now > started) is expect_a_wait


class TestRateLimitPercent:
    @pytest.mark.parametrize(
        "percent, expected_share",
        [(None, None), (25, 0.25), (1, 0.01), (100, 1.0)],
    )
    def test_a_percent_becomes_a_share_and_blank_stays_blank(
        self, percent: int | None, expected_share: float | None
    ) -> None:
        assert parse_rate_limit_percent(percent) == expected_share

    @pytest.mark.parametrize("percent", [0, -5, 101])
    def test_a_percent_outside_the_range_is_rejected(self, percent: int) -> None:
        with pytest.raises(ValueError):
            parse_rate_limit_percent(percent)

    def test_a_configured_share_overrides_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = _FakeClock()
        monkeypatch.setattr(rate_limit_wrapper, "time", clock)
        monkeypatch.setattr(zoom_client, "_DEFAULT_RATE_LIMIT_SHARE", 1.0)
        monkeypatch.setattr(
            zoom_client,
            "_PLAN_CALLS_PER_SECOND",
            {plan: {tier: 2 for tier in ZoomRateLimitTier} for plan in ZoomPlanTier},
        )

        # The default would allow both calls; this connector's own share cuts
        # the budget to one, so the second waits.
        client = ZoomClient(
            account_id="a", client_id="c", client_secret="s", rate_limit_share=0.5
        )
        client._access_token = "tok"
        client._token_expires_at = float("inf")
        client._session = MagicMock()
        client._session.request.return_value = _response(200)

        client._request("GET", "/first")
        started = clock.now
        client._request("GET", "/second")

        assert clock.now > started
