from datetime import datetime
import json
import time
from typing import Any, Dict, List, Optional, Iterator, Tuple, AsyncIterator

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import CredentialsProviderInterface
from onyx.connectors.interfaces import OAuthConnector, PollConnector, CheckpointedConnector
from onyx.connectors.models import (
    Document,
    Section,
    TextSection,
    ConnectorCheckpoint,
    ConnectorFailure,
)


class YouTubeCheckpoint(ConnectorCheckpoint):
    """Checkpoint for YouTube connector."""

    last_poll_time: float
    processed_videos: List[str]
    has_more: bool = False

    def to_json(self) -> Dict[str, Any]:
        """Convert checkpoint to JSON."""
        return {
            "last_poll_time": self.last_poll_time,
            "processed_videos": self.processed_videos,
            "has_more": self.has_more
        }

    @classmethod
    def from_json(cls, json_dict: Dict[str, Any]) -> "YouTubeCheckpoint":
        """Create checkpoint from JSON."""
        return cls(
            last_poll_time=json_dict["last_poll_time"],
            processed_videos=json_dict["processed_videos"],
            has_more=json_dict.get("has_more", False)
        )


class YouTubeConnector(OAuthConnector, PollConnector, CheckpointedConnector[YouTubeCheckpoint]):
    """YouTube connector implementation."""

    def __init__(self) -> None:
        """Initialize the YouTube connector."""
        super().__init__()
        self.youtube = None
        self._credentials_provider = None

    def set_credentials_provider(self, credentials_provider: CredentialsProviderInterface) -> None:
        """Set the credentials provider for the connector.
        
        Args:
            credentials_provider: The credentials provider to use for authentication.
        """
        self._credentials_provider = credentials_provider
        if not self.youtube:
            creds_str = self._credentials_provider.get_credentials()
            creds_dict = json.loads(creds_str)
            credentials = Credentials(
                token=creds_dict["token"],
                refresh_token=creds_dict["refresh_token"],
                token_uri=creds_dict["token_uri"],
                client_id=creds_dict["client_id"],
                client_secret=creds_dict["client_secret"],
                scopes=creds_dict["scopes"]
            )
            self.youtube = build("youtube", "v3", credentials=credentials)

    def load_credentials(self) -> Optional[Credentials]:
        """Load credentials from the provider.
        
        Returns:
            Optional[Credentials]: The loaded credentials if available, None otherwise.
        """
        if not self._credentials_provider:
            return None
        creds_str = self._credentials_provider.get_credentials()
        if not creds_str:
            return None
        creds_dict = json.loads(creds_str)
        return Credentials(
            token=creds_dict["token"],
            refresh_token=creds_dict["refresh_token"],
            token_uri=creds_dict["token_uri"],
            client_id=creds_dict["client_id"],
            client_secret=creds_dict["client_secret"],
            scopes=creds_dict["scopes"]
        )

    @classmethod
    def oauth_id(cls) -> str:
        """Get the OAuth ID for YouTube.
        
        Returns:
            str: The OAuth ID for YouTube.
        """
        return "youtube"

    @property
    def oauth_authorization_url(self) -> str:
        """Get the OAuth authorization URL for YouTube.
        
        Returns:
            str: The OAuth authorization URL.
        """
        return "https://accounts.google.com/o/oauth2/v2/auth"

    @property
    def oauth_token_url(self) -> str:
        """Get the OAuth token URL for YouTube.
        
        Returns:
            str: The OAuth token URL.
        """
        return "https://oauth2.googleapis.com/token"

    @property
    def oauth_scopes(self) -> List[str]:
        """Get the required OAuth scopes for YouTube.
        
        Returns:
            List[str]: List of required OAuth scopes.
        """
        return [
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ]

    def oauth_code_to_token(self, code: str) -> Dict[str, Any]:
        """Exchange OAuth code for tokens.
        
        Args:
            code: The OAuth code to exchange.
            
        Returns:
            Dict[str, Any]: The token response.
            
        Raises:
            ValueError: If credentials provider is not set or no credentials are available.
        """
        if not self._credentials_provider:
            raise ValueError("Credentials provider not set")
        
        credentials = self._credentials_provider.get_credentials()
        if not credentials:
            raise ValueError("No credentials available")
        
        return {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }

    def validate_connector_settings(self) -> None:
        """Validate the connector settings.
        
        Raises:
            ValueError: If YouTube client is not initialized.
        """
        if not self.youtube:
            raise ValueError("YouTube client not initialized")

    def build_dummy_checkpoint(self) -> YouTubeCheckpoint:
        """Build a dummy checkpoint for testing.
        
        Returns:
            YouTubeCheckpoint: A dummy checkpoint instance.
        """
        return YouTubeCheckpoint(
            last_poll_time=time.time(),
            processed_videos=[],
            has_more=True  # ensure that i process at least one batch
        )

    def validate_checkpoint_json(self, checkpoint_json: Dict[str, Any]) -> None:
        """Validate the checkpoint JSON.
        
        Args:
            checkpoint_json: The checkpoint JSON to validate.
            
        Raises:
            ValueError: If required fields are missing.
        """
        required_fields = ["last_poll_time", "processed_videos", "has_more"]
        for field in required_fields:
            if field not in checkpoint_json:
                raise ValueError(f"Missing required field in checkpoint: {field}")

    def load_from_checkpoint(
        self,
        start_time: float,
        end_time: float,
        checkpoint: YouTubeCheckpoint,
    ) -> Iterator[Tuple[Optional[Document], Optional[ConnectorFailure], Optional[YouTubeCheckpoint]]]:
        """Load documents from a checkpoint.
        
        Args:
            start_time: The start time for loading documents.
            end_time: The end time for loading documents.
            checkpoint: The checkpoint to load from.
            
        Yields:
            Tuple[Optional[Document], Optional[ConnectorFailure], Optional[YouTubeCheckpoint]]: 
            The document, failure, and checkpoint.
            
        Raises:
            ValueError: If YouTube client is not initialized.
        """
        if not self.youtube:
            raise ValueError("YouTube client not initialized")

        try:
            search_response = self.youtube.search().list(
                part="snippet",
                maxResults=50,
                order="date",
                publishedAfter=datetime.fromtimestamp(start_time).isoformat() + "Z",
                type="video"
            ).execute()

            for item in search_response.get("items", []):
                video_id = item["id"]["videoId"]
                if video_id in checkpoint.processed_videos:
                    continue

                #video infor
                video_response = self.youtube.videos().list(
                    part="snippet,contentDetails,statistics",
                    id=video_id
                ).execute()

                if not video_response.get("items"):
                    continue

                video = video_response["items"][0]
                snippet = video["snippet"]
                stats = video["statistics"]

                # doc sections
                sections: List[Section] = [
                    TextSection(text=snippet["title"], name="title"),
                    TextSection(text=snippet["description"], name="description"),
                    TextSection(
                        text=f"Channel: {snippet['channelTitle']}\n"
                             f"Views: {stats.get('viewCount', '0')}\n"
                             f"Likes: {stats.get('likeCount', '0')}\n"
                             f"Comments: {stats.get('commentCount', '0')}",
                        name="metadata"
                    )
                ]

                doc = Document(
                    id=video_id,
                    sections=sections,
                    source=DocumentSource.YOUTUBE,
                    semantic_identifier=snippet["title"],
                    metadata={
                        "channel": snippet["channelTitle"],
                        "published_at": snippet["publishedAt"],
                        "views": stats.get("viewCount", "0"),
                        "likes": stats.get("likeCount", "0"),
                        "comments": stats.get("commentCount", "0")
                    }
                )

                checkpoint.processed_videos.append(video_id)
                checkpoint.has_more = len(search_response.get("items", [])) > len(checkpoint.processed_videos)

                yield doc, None, checkpoint

            # if all videos are processes -> set has_more to False
            if len(checkpoint.processed_videos) >= len(search_response.get("items", [])):
                checkpoint.has_more = False

        except HttpError as e:
            yield None, ConnectorFailure(error=f"YouTube API error: {str(e)}"), checkpoint

    async def poll_source(self, start_time: datetime) -> AsyncIterator[List[Document]]:
        """Poll YouTube for new videos.
        
        Args:
            start_time: The start time for polling.
            
        Yields:
            List[Document]: List of documents found.
            
        Raises:
            ValueError: If YouTube client is not initialized or API error occurs.
        """
        if not self.youtube:
            raise ValueError("YouTube client not initialized")

        try:
            search_response = self.youtube.search().list(
                part="snippet",
                maxResults=50,
                order="date",
                publishedAfter=start_time.isoformat() + "Z",
                type="video"
            ).execute()

            for item in search_response.get("items", []):
                video_id = item["id"]["videoId"]

                video_response = self.youtube.videos().list(
                    part="snippet,contentDetails,statistics",
                    id=video_id
                ).execute()

                if not video_response.get("items"):
                    continue

                video = video_response["items"][0]
                snippet = video["snippet"]
                stats = video["statistics"]

                sections: List[Section] = [
                    TextSection(text=snippet["title"], name="title"),
                    TextSection(text=snippet["description"], name="description"),
                    TextSection(
                        text=f"Channel: {snippet['channelTitle']}\n"
                             f"Views: {stats.get('viewCount', '0')}\n"
                             f"Likes: {stats.get('likeCount', '0')}\n"
                             f"Comments: {stats.get('commentCount', '0')}",
                        name="metadata"
                    )
                ]

                yield [Document(
                    id=video_id,
                    sections=sections,
                    source=DocumentSource.YOUTUBE,
                    semantic_identifier=snippet["title"],
                    metadata={
                        "channel": snippet["channelTitle"],
                        "published_at": snippet["publishedAt"],
                        "views": stats.get("viewCount", "0"),
                        "likes": stats.get("likeCount", "0"),
                        "comments": stats.get("commentCount", "0")
                    }
                )]

        except HttpError as e:
            raise ValueError(f"YouTube API error: {str(e)}") 