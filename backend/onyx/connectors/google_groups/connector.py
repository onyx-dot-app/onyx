import datetime
from collections.abc import Generator
from typing import Any
import feedparser

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

class GoogleGroupsConfig(BaseModel):
    group_name: str
    is_public: bool = True

class GoogleGroupsConnector(SlimConnectorWithPermSync):
    def __init__(self, **kwargs: Any) -> None:
        self.config = GoogleGroupsConfig(**kwargs)

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        # Public groups don't require credentials for RSS
        pass

    def _get_rss_url(self) -> str:
        # Standard RSS feed format for Google Groups
        return f"https://groups.google.com/forum/feed/{self.config.group_name}/msgs/rss.xml"

    def retrieve_all_slim_documents(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> Generator[GenerateSlimDocumentOutput, None, None]:
        feed_url = self._get_rss_url()
        feed = feedparser.parse(feed_url)
        
        for entry in feed.entries:
            yield SlimDocument(id=entry.link, perm_sync_data=None)

    def retrieve_full_documents(
        self, slim_documents: list[SlimDocument]
    ) -> Generator[list[Document], None, None]:
        # To avoid re-fetching the feed multiple times, we fetch once here
        feed_url = self._get_rss_url()
        feed = feedparser.parse(feed_url)
        
        # Create a lookup
        entries_by_link = {entry.link: entry for entry in feed.entries}

        for slim_doc in slim_documents:
            entry = entries_by_link.get(slim_doc.id)
            if not entry:
                continue

            try:
                # Handle dates
                create_time = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                create_time = datetime.datetime.now(datetime.timezone.utc)

            text_content = entry.get('summary', '') or entry.get('description', '')
            author = entry.get('author', 'Unknown Author')

            yield [
                Document(
                    id=slim_doc.id,
                    sections=[TextSection(text=f"Author: {author}

{text_content}", link=slim_doc.id)],
                    source=DocumentSource.GOOGLE_GROUPS,
                    semantic_identifier=entry.title,
                    title=entry.title,
                    doc_updated_at=create_time,
                    metadata={
                        "author": author,
                        "group": self.config.group_name,
                    },
                )
            ]

    def stop_sync(self) -> None:
        pass
