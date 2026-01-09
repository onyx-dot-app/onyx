"""Pydantic models for release notes API."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ContentType(str, Enum):
    """Types of content blocks in a release note entry."""

    TEXT = "text"
    HEADING = "heading"
    IMAGE = "image"
    CALLOUT = "callout"


class CalloutVariant(str, Enum):
    """Callout variant types."""

    WARNING = "warning"
    INFO = "info"
    NOTE = "note"
    TIP = "tip"


class ContentSection(BaseModel):
    """A content block within a release note entry.

    Fields are optional based on type:
    - text: content
    - heading: content, level
    - image: src, content (alt text)
    - callout: content, variant
    """

    type: ContentType
    content: str | None = None
    level: int | None = None  # For headings (1-4)
    src: str | None = None  # For images
    variant: CalloutVariant | None = None  # For callouts


class ReleaseNoteEntry(BaseModel):
    """A single version's release note entry."""

    version: str  # e.g., "v2.7.0"
    date: str  # e.g., "January 7th, 2026"
    tags: list[str] = []  # e.g., ["New Features", "Breaking Changes"]
    title: str  # Display title for notifications: "Onyx v2.7.0 is available!"
    sections: list[ContentSection] = []  # Parsed content blocks


class ReleaseNotesResponse(BaseModel):
    """Response model for GET /api/release-notes."""

    entries: list[ReleaseNoteEntry]  # All parsed release note versions
    fetched_at: datetime


class ReleaseNotesCacheData(BaseModel):
    """Internal model for cached release notes data."""

    entries: list[ReleaseNoteEntry]
    fetched_at: datetime
    content_updated: bool = False  # True if new content was fetched (not 304)
