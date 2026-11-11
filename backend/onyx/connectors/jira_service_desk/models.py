from typing import Any
from pydantic import BaseModel, Field
from onyx.connectors.models import ConnectorCheckpoint


class JSMRequestType(BaseModel):
    id: str
    name: str
    description: str | None = None
    help_text: str | None = None


class JSMServiceDesk(BaseModel):
    id: str
    project_id: str = Field(alias="projectId")
    project_key: str = Field(alias="projectKey")
    project_name: str = Field(alias="projectName")


class JSMCustomerRequest(BaseModel):
    issue_id: str = Field(alias="issueId")
    issue_key: str = Field(alias="issueKey")
    request_type_id: str | None = Field(default=None, alias="requestTypeId")
    service_desk_id: str | None = Field(default=None, alias="serviceDeskId")
    created_date: str | None = Field(default=None, alias="createdDate")
    summary: str
    description: str | None = None
    reporter_name: str | None = None
    status: str | None = None
    priority: str | None = None
    raw_fields: dict[str, Any] = Field(default_factory=dict)


class JSMConnectorCheckpoint(ConnectorCheckpoint):
    last_synced_epoch: int = 0
    synced_issue_keys: list[str] = Field(default_factory=list)
