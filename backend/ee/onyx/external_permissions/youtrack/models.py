from pydantic import BaseModel, Field


class VisibilityEntries(BaseModel):
    """The groups and users a restricted issue names. The reporter counts as a
    named user, since YouTrack lets them read their own restricted issue."""

    group_ids: set[str] = Field(default_factory=set)
    user_ids: set[str] = Field(default_factory=set)


class ProjectReaders(BaseModel):
    """User ids that can read a project's issues, and those of them that can
    also read past visibility restrictions."""

    readers: set[str]
    overriders: set[str]
