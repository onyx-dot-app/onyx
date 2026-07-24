"""Pydantic models for the Jira Service Management connector.

JSM is a separate Atlassian product that exposes a different REST surface
than core Jira. Core Jira uses ``/rest/api/3/`` and works with ``Issue``
resources; JSM uses ``/rest/servicedeskapi/`` and exposes ``Request`` resources
that are *backed* by Jira issues but carry additional service-desk metadata
(SLAs, request types, customer fields, organizations).

References:
    https://developer.atlassian.com/cloud/jira/service-desk/rest/intro/
    https://developer.atlassian.com/cloud/jira/service-desk/rest/api-group-request/
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import Field


class JsmCustomer(BaseModel):
    """A reporter / participant on a JSM request."""

    account_id: str | None = None
    display_name: str | None = None
    email: str | None = None


class JsmRequestType(BaseModel):
    """The request-type a customer raised the ticket under."""

    id: str
    name: str
    description: str | None = None


class JsmRequest(BaseModel):
    """A single JSM customer request, normalised from the raw API shape."""

    issue_key: str
    request_type: JsmRequestType | None = None
    service_desk_id: str
    summary: str
    description: str | None = None
    status: str
    priority: str | None = None
    reporter: JsmCustomer | None = None
    participants: list[JsmCustomer] = Field(default_factory=list)
    organization_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    web_url: str
    raw: dict[str, Any] = Field(default_factory=dict)
