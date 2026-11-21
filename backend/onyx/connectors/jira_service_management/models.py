from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class JSMServiceDesk(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    project_name: str = Field(alias="projectName")
    project_key: str = Field(alias="projectKey")


class JSMRequestType(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: Optional[str] = None
    service_desk_id: Optional[str] = Field(default=None, alias="serviceDeskId")
    issue_type_id: Optional[str] = Field(default=None, alias="issueTypeId")


class JSMComment(BaseModel):
    id: str
    body: str
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    created: Optional[datetime] = None
    is_public: bool = True


class JSMRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    issue_id: str = Field(alias="issueId")
    issue_key: str = Field(alias="issueKey")
    summary: str
    description: Optional[str] = None
    service_desk_id: str = Field(alias="serviceDeskId")
    service_desk_project_key: Optional[str] = None
    request_type_id: Optional[str] = None
    request_type_name: Optional[str] = None
    status: str
    reporter_name: Optional[str] = None
    reporter_email: Optional[str] = None
    assignee_name: Optional[str] = None
    assignee_email: Optional[str] = None
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None
    comments: list[JSMComment] = Field(default_factory=list)
    raw_fields: dict[str, Any] = Field(default_factory=dict)
