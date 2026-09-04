from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.zoom.client import ZoomClient, _encode_meeting_identifier


def _response(status: int, payload: Any = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    response.text = text
    response.raise_for_status.side_effect = None
    return response


def _client() -> ZoomClient:
    client = ZoomClient(account_id="acct", client_id="cid", client_secret="secret")
    # Skip the OAuth round trip; token handling has its own tests below.
    client._access_token = "tok"
    client._token_expires_at = float("inf")
    return client


class TestEncodeMeetingIdentifier:
    """Zoom's docs require encoding a uuid twice when it starts with "/" or
    contains "//", because something in front of their API decodes one layer
    before the request arrives."""

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
    @patch("onyx.connectors.zoom.client.requests.post")
    def test_token_is_fetched_once_and_reused(self, post: MagicMock) -> None:
        post.return_value = _response(200, {"access_token": "t1", "expires_in": 3600})
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")

        assert client._get_access_token() == "t1"
        assert client._get_access_token() == "t1"

        assert post.call_count == 1
        assert post.call_args.kwargs["params"] == {
            "grant_type": "account_credentials",
            "account_id": "a",
        }
        assert post.call_args.kwargs["auth"] == ("c", "s")

    @patch("onyx.connectors.zoom.client.requests.post")
    def test_token_is_refreshed_before_it_expires(self, post: MagicMock) -> None:
        post.side_effect = [
            _response(200, {"access_token": "t1", "expires_in": 3600}),
            _response(200, {"access_token": "t2", "expires_in": 3600}),
        ]
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")
        assert client._get_access_token() == "t1"

        # Inside the refresh margin: a request must not go out holding a token
        # that lapses mid-flight.
        client._token_expires_at = 0.0

        assert client._get_access_token() == "t2"
        assert post.call_count == 2

    @patch("onyx.connectors.zoom.client.requests.post")
    def test_rejected_credentials_raise_a_typed_error(self, post: MagicMock) -> None:
        post.return_value = _response(401)
        client = ZoomClient(account_id="a", client_id="c", client_secret="s")

        with pytest.raises(CredentialExpiredError):
            client._get_access_token()


class TestRequestErrorMapping:
    def test_unauthorized_raises_credential_expired(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(401)

        with pytest.raises(CredentialExpiredError):
            client._request("GET", "/anything")

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
        client._session.request.return_value = _response(
            200,
            {
                "download_url": "https://zoom.example/t.vtt",
                "download_restriction_reason": "NOT_READY",
            },
        )

        transcript = client.get_meeting_transcript("111")

        assert transcript is not None
        assert transcript.download_url == "https://zoom.example/t.vtt"
        assert transcript.download_restriction_reason == "NOT_READY"

    def test_404_means_never_recorded_not_an_error(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        assert client.get_meeting_transcript("111") is None

    def test_identifier_is_encoded_into_the_path(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {})

        client.get_meeting_transcript("ab/cd==")

        url = client._session.request.call_args.args[1]
        assert "ab%2Fcd%3D%3D" in url
        assert "ab/cd==" not in url


class TestGetPastMeetingDetails:
    def test_parses_the_response(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(
            200, {"topic": "Weekly Sync", "start_time": "2026-01-15T10:00:00Z"}
        )

        details = client.get_past_meeting_details("111")

        assert details is not None
        assert details.topic == "Weekly Sync"
        assert details.start_time == "2026-01-15T10:00:00Z"

    def test_404_returns_none(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        assert client.get_past_meeting_details("111") is None


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

    def test_404_yields_an_empty_list(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(404)

        assert client.list_past_meeting_occurrences("111") == []

    def test_missing_meetings_key_yields_an_empty_list(self) -> None:
        client = _client()
        client._session = MagicMock()
        client._session.request.return_value = _response(200, {})

        assert client.list_past_meeting_occurrences("111") == []


class TestDownloadTranscriptVtt:
    @patch("onyx.connectors.zoom.client.requests.get")
    def test_returns_body_and_authenticates(self, get: MagicMock) -> None:
        get.return_value = _response(200, text="WEBVTT\n")
        client = _client()

        body = client.download_transcript_vtt("https://zoom.example/t.vtt")

        assert body == "WEBVTT\n"
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
