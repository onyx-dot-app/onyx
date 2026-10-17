"""Pydantic models for Jira Service Management connector."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JSMCustomer(BaseModel):
    """Represents a JSM customer (requester)."""

    account_id: str | None = None
    name: str | None = None
    email: str | None = None
    display_name: str | None = None
    active: bool = True


class JSMComment(BaseModel):
    """Represents a comment on a JSM ticket."""

    id: str
    author_name: str | None = None
    author_email: str | None = None
    body: str = ""
    created: datetime | None = None
    updated: datetime | None = None
    is_public: bool = True


class JSMServiceDesk(BaseModel):
    """Represents a Jira Service Management service desk."""

    id: str
    name: str
    project_key: str
    project_name: str | None = None
    description: str | None = None


class JSMAttachment(BaseModel):
    """Metadata for a JSM ticket attachment."""

    id: str
    filename: str
    size: int = 0
    content_type: str | None = None
    author: str | None = None
    created: datetime | None = None
    download_url: str | None = None


class JSMTicket(BaseModel):
    """Represents a Jira Service Management ticket / customer request."""

    id: str
    key: str
    summary: str = ""
    description: str = ""
    status: str | None = None
    status_category: str | None = None
    priority: str | None = None
    resolution: str | None = None
    issue_type: str | None = None
    created: datetime | None = None
    updated: datetime | None = None
    resolved: datetime | None = None
    due_date: datetime | None = None
    service_desk_id: str | None = None
    request_type_id: str | None = None
    request_type_name: str | None = None
    reporter: JSMCustomer | None = None
    assignee_name: str | None = None
    assignee_email: str | None = None
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    comments: list[JSMComment] = Field(default_factory=list)
    attachments: list[JSMAttachment] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
