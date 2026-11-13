"""Typed shapes of the Jira Service Management (servicedesk) REST API.

The servicedesk API is separate from the Jira issue API: it knows requests,
their visibility-marked comments, and SLAs. Payloads vary between Cloud and
Server / Data Center, so every field is optional and unknown keys are kept.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class JsmServiceDesk(BaseModel):
    """One service desk: ``GET /rest/servicedeskapi/servicedesk`` values."""

    model_config = ConfigDict(extra="allow")

    id: str
    project_key: str
    project_name: str | None = None


class JsmRequest(BaseModel):
    """One request: ``GET /rest/servicedeskapi/request/{issueIdOrKey}``."""

    model_config = ConfigDict(extra="allow")

    issue_id: str | None = None
    issue_key: str | None = None
    request_type_name: str | None = None
    status: str | None = None
    service_desk_id: str | None = None
    service_desk_name: str | None = None
    reporter_name: str | None = None
    organizations: list[str] = []
    created: str | None = None
    updated: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "JsmRequest":
        request_type: Any = raw.get("requestType")
        service_desk: Any = raw.get("serviceDesk")
        reporter: Any = raw.get("reporter")
        organizations: Any = raw.get("organization")
        return cls(
            issue_id=_str_or_none(raw.get("issueId")),
            issue_key=_str_or_none(raw.get("issueKey")),
            request_type_name=_name_or_none(request_type),
            status=_name_or_none(raw.get("currentStatus") or raw.get("status")),
            service_desk_id=_str_or_none(service_desk.get("id"))
            if isinstance(service_desk, dict)
            else None,
            service_desk_name=_name_or_none(service_desk),
            reporter_name=_display_name_or_none(reporter),
            organizations=[
                name
                for org in organizations
                if isinstance(org, dict) and isinstance((name := _name_or_none(org)), str)
            ]
            if isinstance(organizations, list)
            else [],
            created=_str_or_none(raw.get("createdDate")),
            updated=_str_or_none(raw.get("updatedDate")),
        )


class JsmComment(BaseModel):
    """One request comment with its customer-visible flag."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    body: Any = None
    author_name: str | None = None
    author_email: str | None = None
    public: bool = True
    created: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "JsmComment":
        author: Any = raw.get("author")
        return cls(
            id=_str_or_none(raw.get("id")),
            body=raw.get("body"),
            author_name=_display_name_or_none(author),
            author_email=_email_or_none(author),
            # The servicedesk API marks agent-only comments ``public: false``.
            public=bool(raw.get("public", True)),
            created=_str_or_none(raw.get("created")),
        )


class JsmSla(BaseModel):
    """One SLA metric of a request: ``/rest/servicedeskapi/request/{key}/sla``."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    breached: bool | None = None
    # Human-readable goal, e.g. "4h".
    goal: str | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "JsmSla":
        ongoing: Any = raw.get("ongoingCycle")
        completed: Any = raw.get("completedCycles")
        breached: bool | None = None
        if isinstance(ongoing, dict):
            breached = bool(ongoing.get("breached"))
        elif isinstance(completed, list) and completed:
            last: Any = completed[-1]
            if isinstance(last, dict):
                breached = bool(last.get("breached"))
        goal_duration: Any = raw.get("goalDuration")
        goal: str | None = None
        if isinstance(goal_duration, dict):
            goal = _str_or_none(goal_duration.get("friendly"))
        return cls(
            name=_name_or_none(raw) or _str_or_none(raw.get("name")),
            breached=breached,
            goal=goal,
        )


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _name_or_none(value: Any) -> str | None:
    if isinstance(value, dict):
        return _str_or_none(value.get("name"))
    return _str_or_none(value)


def _display_name_or_none(value: Any) -> str | None:
    """User objects carry ``displayName``; named objects carry ``name``."""
    if isinstance(value, dict):
        return _str_or_none(value.get("displayName")) or _str_or_none(value.get("name"))
    return _str_or_none(value)


def _email_or_none(value: Any) -> str | None:
    if isinstance(value, dict):
        return _str_or_none(value.get("emailAddress"))
    return None
