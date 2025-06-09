import time
from unittest.mock import MagicMock, patch
import pytest
from googleapiclient.errors import HttpError

from onyx.connectors.youtube.connector import YouTubeConnector
from onyx.connectors.credentials_provider import CredentialsProviderInterface
from onyx.connectors.models import Document, Section, TextSection
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector, to_sections, to_text_sections


@pytest.fixture
def mock_youtube_client():
    """Create a mock YouTube client."""
    mock_client = MagicMock()
    
    # mocking search resp
    mock_search_response = {
        "items": [
            {
                "id": {"videoId": "test_video_id"},
                "snippet": {
                    "title": "Test Video",
                    "description": "Test Description",
                    "channelTitle": "Test Channel",
                    "publishedAt": "2024-01-01T00:00:00Z"
                }
            }
        ]
    }
    
    # mocking video resp
    mock_video_response = {
        "items": [
            {
                "id": "test_video_id",
                "snippet": {
                    "title": "Test Video",
                    "description": "Test Description",
                    "channelTitle": "Test Channel",
                    "publishedAt": "2024-01-01T00:00:00Z"
                },
                "statistics": {
                    "viewCount": "1000",
                    "likeCount": "100",
                    "commentCount": "50"
                }
            }
        ]
    }

    mock_search = MagicMock()
    mock_search.list.return_value.execute.return_value = mock_search_response
    
    mock_videos = MagicMock()
    mock_videos.list.return_value.execute.return_value = mock_video_response
    
    mock_client.search.return_value = mock_search
    mock_client.videos.return_value = mock_videos
    
    return mock_client


@pytest.fixture
def youtube_connector(mock_youtube_client):
    """Create a YouTube connector with mocked client."""
    connector = YouTubeConnector()
    connector.youtube = mock_youtube_client
    return connector


@pytest.fixture
def youtube_credentials_provider():
    """Create a mock credentials provider."""
    provider = MagicMock(spec=CredentialsProviderInterface)
    provider.get_credentials.return_value = '{"token": "test_token", "refresh_token": "test_refresh", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "test_client_id", "client_secret": "test_client_secret", "scopes": ["https://www.googleapis.com/auth/youtube.readonly"]}'
    return provider


def test_validate_youtube_connector_settings(
    youtube_connector: YouTubeConnector,
) -> None:
    """Test validating YouTube connector settings."""
    youtube_connector.validate_connector_settings()


@pytest.mark.asyncio
async def test_indexing_videos(
    youtube_connector: YouTubeConnector,
) -> None:
    """Test indexing videos from YouTube."""
    if not youtube_connector.youtube:
        raise RuntimeError("YouTube client must be defined")

    docs = load_all_docs_from_checkpoint_connector(
        connector=youtube_connector,
        start=0.0,
        end=time.time(),
    )

    actual_descriptions = set(to_text_sections(to_sections(docs)))
    expected_descriptions = {"Test Description"}
    assert expected_descriptions == actual_descriptions


@pytest.mark.asyncio
async def test_indexing_with_api_error(
    youtube_connector: YouTubeConnector,
) -> None:
    """Test handling of API errors during indexing."""
    if not youtube_connector.youtube:
        raise RuntimeError("YouTube client must be defined")

    # mock an api error
    youtube_connector.youtube.search().list(part="snippet").execute.side_effect = HttpError(
        resp=MagicMock(status=403),
        content=b"API Error"
    )

    with pytest.raises(RuntimeError, match="Failed to load documents"):
        load_all_docs_from_checkpoint_connector(
            connector=youtube_connector,
            start=0.0,
            end=time.time(),
        ) 