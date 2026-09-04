from unittest.mock import MagicMock

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomMeetingOccurrence, ZoomPastMeetingDetails
from onyx.connectors.zoom.recordings.models import ZoomSessionType
from onyx.connectors.zoom.recordings.session_types import (
    MeetingSessionType,
    get_session_type_handler,
)


class TestGetSessionTypeHandler:
    def test_meeting_resolves_to_meeting_handler(self) -> None:
        handler = get_session_type_handler(ZoomSessionType.MEETING)
        assert isinstance(handler, MeetingSessionType)
        assert handler.session_type == ZoomSessionType.MEETING


class TestMeetingSessionType:
    def test_list_occurrences_delegates_to_meeting_endpoint(self) -> None:
        mock_client = MagicMock(spec=ZoomClient)
        mock_client.list_past_meeting_occurrences.return_value = [
            ZoomMeetingOccurrence(uuid="uuid-1")
        ]

        result = MeetingSessionType().list_occurrences(mock_client, "111")

        mock_client.list_past_meeting_occurrences.assert_called_once_with("111")
        assert result == [ZoomMeetingOccurrence(uuid="uuid-1")]

    def test_get_occurrence_details_delegates_to_meeting_endpoint(self) -> None:
        mock_client = MagicMock(spec=ZoomClient)
        mock_client.get_past_meeting_details.return_value = ZoomPastMeetingDetails(
            topic="Weekly Sync"
        )

        result = MeetingSessionType().get_occurrence_details(mock_client, "uuid-1")

        mock_client.get_past_meeting_details.assert_called_once_with("uuid-1")
        assert result == ZoomPastMeetingDetails(topic="Weekly Sync")
