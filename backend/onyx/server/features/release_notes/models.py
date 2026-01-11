"""Pydantic models for release notes."""

from pydantic import BaseModel


class ReleaseNoteEntry(BaseModel):
    """A single version's release note entry."""

    version: str  # e.g., "v2.7.0"
    date: str  # e.g., "January 7th, 2026"
    title: str  # Display title for notifications: "Onyx v2.7.0 is available!"
