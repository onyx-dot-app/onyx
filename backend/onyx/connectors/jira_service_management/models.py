from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JsmServiceDesk(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int | None = Field(default=None, alias="id")
    project_id: int | None = Field(default=None, alias="projectId")
    project_key: str | None = Field(default=None, alias="projectKey")
    project_name: str | None = Field(default=None, alias="projectName")


class JsmRequestFieldValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    field_id: int | None = Field(default=None, alias="fieldId")
    name: str | None = Field(default=None, alias="name")
    # The API value can be a string, number, object, or list.
    value: Any = Field(default=None, alias="value")


class JsmRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    issue_id: int | None = Field(default=None, alias="issueId")
    issue_key: str | None = Field(default=None, alias="issueKey")
    request_type_id: int | None = Field(default=None, alias="requestTypeId")
    service_desk_id: int | None = Field(default=None, alias="serviceDeskId")
    created_date: str | None = Field(default=None, alias="createdDate")
    reporter: dict[str, Any] | None = Field(default=None, alias="reporter")
    request_field_values: list[JsmRequestFieldValue] | None = Field(
        default=None, alias="requestFieldValues"
    )
    current_status: dict[str, Any] | None = Field(default=None, alias="currentStatus")


class JsmComment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int | None = Field(default=None, alias="id")
    body: str | None = Field(default=None, alias="body")
    public: bool | None = Field(default=None, alias="public")
    author: dict[str, Any] | None = Field(default=None, alias="author")
    created: str | None = Field(default=None, alias="created")
