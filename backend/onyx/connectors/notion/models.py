from typing import Any
from typing import Optional

from pydantic import BaseModel


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


class NotionSearchResponse(BaseModel):
    """Represents the response from the Notion Search API"""

    results: list[dict[str, Any]]
    next_cursor: Optional[str]
    has_more: bool = False
