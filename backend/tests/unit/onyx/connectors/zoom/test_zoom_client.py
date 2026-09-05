from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest
import requests
from requests.adapters import HTTPAdapter

from onyx.connectors.exceptions import (
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.zoom.client import (
    _API_BASE_URL,
    _OAUTH_TOKEN_URL,
    _ZOOM_HOST,
    ZoomClient,
    _encode_meeting_identifier,
    _reject_non_zoom_download_url,
)
from onyx.connectors.zoom.models import ZoomTranscript

_ZOOM_DOWNLOAD_URL = "https://zoom.us/rec/download/abc.vtt"

# Zoom's own documented example, which returns all three readiness fields at
# once even though their field docs say that cannot happen.
_DOCUMENTED_TRANSCRIPT = {
    "meeting_id": "uaFkQyFCSwya8iNYtkAw3A==",
    "meeting_topic": "My Personal Meeting",
    "host_id": "_0ctZtY0REqWalTmwvrdIw",
    "transcript_created_time": "2025-06-27T13:48:24Z",
    "can_download": True,
    "download_url": "https://zoom.example/t.vtt",
    "download_restriction_reason": "NOT_READY",
}


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
        assert 429 in adapter.max_retries.status_forcelist


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

    def test_the_allowlist_tracks_whichever_zoom_the_client_talks_to(self) -> None:
        # Point the client at Zoom for Government without moving the allowlist
        # and every download fails as a non-Zoom host.
        api_host = urlparse(_API_BASE_URL).hostname or ""
        assert api_host == _ZOOM_HOST or api_host.endswith(f".{_ZOOM_HOST}")

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
        transcript = ZoomTranscript(can_download=True, download_url=_ZOOM_DOWNLOAD_URL)

        assert transcript.is_downloadable is True

    def test_a_missing_can_download_still_counts_as_ready(self) -> None:
        # The field is absent on older responses, and reading absent as a refusal
        # would index nothing at all.
        transcript = ZoomTranscript(download_url=_ZOOM_DOWNLOAD_URL)

        assert transcript.is_downloadable is True

    @pytest.mark.parametrize(
        "transcript",
        [
            ZoomTranscript(can_download=False, download_url=_ZOOM_DOWNLOAD_URL),
            ZoomTranscript(can_download=True, download_url=None),
            ZoomTranscript(
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
