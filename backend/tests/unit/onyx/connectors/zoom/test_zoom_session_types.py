from unittest.mock import MagicMock

import pytest

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomSessionDetails, ZoomSessionOccurrence
from onyx.connectors.zoom.recordings.models import ZoomSessionType
from onyx.connectors.zoom.recordings.session_types import (
    MeetingSessionType,
    WebinarSessionType,
    get_session_type_handler,
    is_portal_upload,
    session_type_for_recording,
)


class TestGetSessionTypeHandler:
    def test_meeting_resolves_to_meeting_handler(self) -> None:
        handler = get_session_type_handler(ZoomSessionType.MEETING)
        assert isinstance(handler, MeetingSessionType)
        assert handler.session_type == ZoomSessionType.MEETING

    def test_webinar_resolves_to_webinar_handler(self) -> None:
        handler = get_session_type_handler(ZoomSessionType.WEBINAR)
        assert isinstance(handler, WebinarSessionType)
        assert handler.session_type == ZoomSessionType.WEBINAR

    def test_every_session_type_has_a_handler(self) -> None:
        # A type with no entry raises KeyError deep inside discovery, so catch
        # a new one here instead.
        for session_type in ZoomSessionType:
            assert get_session_type_handler(session_type) is not None


class TestMeetingSessionType:
    def test_list_occurrences_delegates_to_meeting_endpoint(self) -> None:
        mock_client = MagicMock(spec=ZoomClient)
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomSessionOccurrence(uuid="uuid-1")
        ]

        result = MeetingSessionType().list_occurrences(mock_client, "111")

        mock_client.list_past_meeting_occurrences.assert_called_once_with("111")
        assert result == [ZoomSessionOccurrence(uuid="uuid-1")]

    def test_get_occurrence_details_delegates_to_meeting_endpoint(self) -> None:
        mock_client = MagicMock(spec=ZoomClient)
        mock_client.get_past_meeting_details.return_value = ZoomSessionDetails(
            topic="Weekly Sync"
        )

        result = MeetingSessionType().get_occurrence_details(mock_client, "uuid-1")

        mock_client.get_past_meeting_details.assert_called_once_with("uuid-1")
        assert result == ZoomSessionDetails(topic="Weekly Sync")


class TestWebinarSessionType:
    def test_list_occurrences_delegates_to_the_webinar_endpoint(self) -> None:
        mock_client = MagicMock(spec=ZoomClient)
        mock_client.list_past_webinar_occurrences.return_value = [
            ZoomSessionOccurrence(uuid="uuid-1")
        ]

        result = WebinarSessionType().list_occurrences(mock_client, "222")

        mock_client.list_past_webinar_occurrences.assert_called_once_with("222")
        mock_client.list_past_meeting_occurrences.assert_not_called()
        assert result == [ZoomSessionOccurrence(uuid="uuid-1")]

    def test_get_occurrence_details_delegates_to_the_webinar_endpoint(self) -> None:
        mock_client = MagicMock(spec=ZoomClient)
        mock_client.get_webinar_details.return_value = ZoomSessionDetails(
            topic="Product Launch"
        )

        result = WebinarSessionType().get_occurrence_details(mock_client, "uuid-1")

        mock_client.get_webinar_details.assert_called_once_with("uuid-1")
        mock_client.get_past_meeting_details.assert_not_called()
        assert result == ZoomSessionDetails(topic="Product Launch")


class TestSessionTypeForRecording:
    """The recording listing is the only discovery path that has to work out a
    session's type at runtime — the ID allowlist has the admin declare it."""

    @pytest.mark.parametrize("code", ["1", "2", "3", "4", "7", "8"])
    def test_every_meeting_code_is_a_meeting(self, code: str) -> None:
        assert session_type_for_recording(code) == ZoomSessionType.MEETING

    @pytest.mark.parametrize("code", ["5", "6", "9"])
    def test_every_webinar_code_is_a_webinar(self, code: str) -> None:
        assert session_type_for_recording(code) == ZoomSessionType.WEBINAR

    def test_an_integer_code_is_read_the_same_as_a_string_one(self) -> None:
        # Zoom documents these as strings and sends them as integers.
        assert session_type_for_recording(5) == ZoomSessionType.WEBINAR
        assert session_type_for_recording(2) == ZoomSessionType.MEETING

    def test_a_portal_upload_is_no_session_at_all(self) -> None:
        assert session_type_for_recording("99") is None
        assert is_portal_upload("99") is True

    def test_an_unknown_or_missing_code_is_no_session_either(self) -> None:
        # A document id freezes the session type and ticket 04 picks the
        # access-list endpoint from it, so a wrong guess can never be undone.
        assert session_type_for_recording("42") is None
        assert session_type_for_recording(None) is None

    def test_an_unknown_code_is_not_mistaken_for_a_portal_upload(self) -> None:
        # The two skip for different reasons and only one of them is expected.
        assert is_portal_upload("42") is False
        assert is_portal_upload(None) is False
