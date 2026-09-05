from unittest.mock import MagicMock

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomSessionDetails, ZoomSessionOccurrence
from onyx.connectors.zoom.recordings.models import ZoomSessionType
from onyx.connectors.zoom.recordings.session_types import (
    MeetingSessionType,
    WebinarSessionType,
    get_session_type_handler,
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
