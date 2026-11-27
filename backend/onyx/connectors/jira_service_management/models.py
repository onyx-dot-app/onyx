"""Jira Service Management entities the connector reads.

Unknown keys are ignored. Jira adds fields by expand and by site, and a
strict model would break a normal response.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# Jira sends these as numbers on some sites and as strings on others.
_ID_FIELDS: frozenset[str] = frozenset(
    {"id", "issue_id", "service_desk_id", "project_id", "account_id"}
)


class _JsmEntity(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @field_validator("*", mode="before")
    @classmethod
    def _stringify_ids(cls, value: Any, info: ValidationInfo) -> Any:
        if (
            info.field_name in _ID_FIELDS
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            return str(value)
        return value


class JsmDate(_JsmEntity):
    iso8601: str | None = None
    epoch_millis: int | None = Field(default=None, alias="epochMillis")


class JsmUser(_JsmEntity):
    account_id: str | None = Field(default=None, alias="accountId")
    display_name: str | None = Field(default=None, alias="displayName")
    email_address: str | None = Field(default=None, alias="emailAddress")
    # Data Center user name. Cloud uses displayName.
    name: str | None = None

    def label(self) -> str | None:
        return self.display_name or self.name or self.email_address


class ServiceDesk(_JsmEntity):
    id: str
    project_id: str = Field(alias="projectId")
    project_key: str = Field(alias="projectKey")
    project_name: str = Field(alias="projectName")


class ServiceDeskPage(_JsmEntity):
    values: list[ServiceDesk] = Field(default_factory=list)
    # None when the response omits the flag. A short page then ends the walk.
    is_last_page: bool | None = Field(default=None, alias="isLastPage")
    size: int = 0


class RequestType(_JsmEntity):
    id: str | None = None
    name: str | None = None


class RequestStatus(_JsmEntity):
    status: str | None = None
    status_date: JsmDate | None = Field(default=None, alias="statusDate")


class RequestField(_JsmEntity):
    field_id: str = Field(alias="fieldId")
    label: str | None = None
    value: Any = None


class ParticipantPage(_JsmEntity):
    values: list[JsmUser] = Field(default_factory=list)


class CustomerRequest(_JsmEntity):
    issue_id: str = Field(alias="issueId")
    issue_key: str = Field(alias="issueKey")
    service_desk_id: str | None = Field(default=None, alias="serviceDeskId")
    created_date: JsmDate | None = Field(default=None, alias="createdDate")
    reporter: JsmUser | None = None
    request_field_values: list[RequestField] = Field(
        default_factory=list, alias="requestFieldValues"
    )
    current_status: RequestStatus | None = Field(default=None, alias="currentStatus")
    request_type: RequestType | None = Field(default=None, alias="requestType")
    participants: ParticipantPage | None = None

    def field_text_source(self, field_id: str) -> Any:
        for field in self.request_field_values:
            if field.field_id == field_id:
                return field.value
        return None


class RequestPage(_JsmEntity):
    values: list[CustomerRequest] = Field(default_factory=list)
    # None when the response omits the flag. A short page then ends the walk.
    is_last_page: bool | None = Field(default=None, alias="isLastPage")
    size: int = 0


class CustomerComment(_JsmEntity):
    id: str
    body: Any = None
    # Omitted means the site did not say. The connector treats that as public
    # so a customer comment is not dropped by a missing flag.
    public: bool = True
    author: JsmUser | None = None
    created: JsmDate | None = None


class CommentPage(_JsmEntity):
    values: list[CustomerComment] = Field(default_factory=list)
    is_last_page: bool | None = Field(default=None, alias="isLastPage")
    size: int = 0


class IssueRef(_JsmEntity):
    id: str | None = None
    key: str


class IssueTimestamps(_JsmEntity):
    """The Jira issue's own created and updated times, not the service desk dates."""

    updated: str
    created: str | None = None


class IssueSearchPage(_JsmEntity):
    """One page of a Jira issue search.

    Cloud pages continue with ``next_page_token``. Server and Data Center
    pages continue with an offset the caller tracks.
    """

    issues: list[IssueRef] = Field(default_factory=list)
    is_last: bool = True
    next_page_token: str | None = None
    uses_token: bool = False
