from typing import Any

from pydantic import BaseModel
from pydantic import field_validator

from onyx.connectors.models import ConnectorCheckpoint


class NotionPage(BaseModel):
    """Represents a Notion Page object"""

    id: str
    created_time: str
    last_edited_time: str
    archived: bool
    properties: dict[str, Any]
    url: str

    database_name: str | None = None  # Only applicable to the database type page (wiki)


class NotionBlock(BaseModel):
    """Represents a Notion Block object"""

    id: str  # Used for the URL
    text: str
    # In a plaintext representation of the page, how this block should be joined
    # with the existing text up to this point, separated out from text for clarity
    prefix: str


class NotionConnectorCheckpoint(ConnectorCheckpoint):
    """Checkpoint for Notion connector tracking traversal state.

    Tracks which pages have been processed and maintains a queue of pages
    to process during recursive traversal.
    """

    # Set of page IDs that have been fully processed (indexed)
    # Stored as list for JSON serialization, converted to set when used
    processed_page_ids: list[str]

    # Queue of page IDs waiting to be processed
    page_queue: list[str]

    # Root page ID if specified (for scoped indexing)
    root_page_id: str | None = None

    @field_validator("processed_page_ids", mode="before")
    @classmethod
    def convert_set_to_list(cls, v: set[str] | list[str]) -> list[str]:
        """Convert set to list for serialization."""
        if isinstance(v, set):
            return list(v)
        return v

    def get_processed_set(self) -> set[str]:
        """Get processed_page_ids as a set for efficient lookups."""
        return set(self.processed_page_ids)

    def add_processed(self, page_id: str) -> None:
        """Add a page ID to processed set."""
        if page_id not in self.processed_page_ids:
            self.processed_page_ids.append(page_id)
