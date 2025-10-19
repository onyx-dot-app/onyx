from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class ErrorApiResponseBody(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    errors: Optional[list[str]] = Field(None, description="The list of errors.")
    exists_id: Optional[str] = Field(
        None,
        description="The ID of the object that already exists if this is a duplicate object error.",
    )
    request_id: Optional[str] = Field(None, description="The request ID for tracking.")


class GetIssueResponseBody(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    data: Optional[Issue] = None
    request_id: Optional[str] = Field(None, description="The request ID for tracking.")


class GetIssuesResponseBody(BaseModel):
    """
    The response body for GET /issues.
    Openapi spec describes pagination, but in practice it is not returned and ignored by the API.
    Therefore, the field is ignored in ingestion.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    data: Optional[list[Issue]] = Field(
        None, description="The data payload of the response."
    )
    pagination: Optional[Pagination] = None
    request_id: Optional[str] = Field(None, description="The request ID for tracking.")


class GetIssueMessagesResponseBody(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    data: Optional[list[Message]] = Field(
        None, description="The data payload of the response."
    )
    pagination: Optional[Pagination] = None
    request_id: Optional[str] = Field(None, description="The request ID for tracking.")


class Message(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    author: Optional[MessageAuthor] = None
    email_info: Optional[EmailMessageInfo] = None
    file_urls: Optional[list[str]] = Field(
        None, description="The URLs of the files in the message, if any."
    )
    id: Optional[str] = Field(None, description="The ID of the message.")
    is_private: Optional[bool] = Field(
        None, description="Indicates if the message is private."
    )
    message_html: Optional[str] = Field(
        None, description="The HTML body of the message."
    )
    source: Optional[str] = Field(None, description="The source of the message.")
    thread_id: Optional[str] = Field(
        None,
        description="The ID of the thread the message belongs to. This is only set for internal notes.",
    )
    timestamp: Optional[str] = Field(
        None, description="The time at which the message was created."
    )


class MessageAuthor(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    avatar_url: Optional[str] = None
    contact: Optional[MiniContact] = None
    name: Optional[str] = None
    user: Optional[MiniUser] = None


class EmailMessageInfo(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    bcc_emails: Optional[list[str]] = Field(
        None, description="The email addresses of the BCC recipients of the message."
    )
    cc_emails: Optional[list[str]] = Field(
        None, description="The email addresses of the CC recipients of the message."
    )
    from_email: Optional[str] = Field(
        None, description="The email address of the sender of the message."
    )
    to_emails: Optional[list[str]] = Field(
        None, description="The email addresses of the recipients of the message."
    )


class Issue(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    account: Optional[MiniAccount] = None
    assignee: Optional[MiniUser] = None
    attachment_urls: Optional[list[str]] = Field(
        None, description="The attachment URLs attached to this issue, if any."
    )
    body_html: Optional[str] = Field(
        None, description="The body of the issue in HTML format."
    )
    business_hours_first_response_seconds: Optional[int] = Field(
        None,
        description="The business hours time in seconds it took for the first response to the issue, if any.",
    )
    business_hours_resolution_seconds: Optional[int] = Field(
        None,
        description="The business hours time in seconds it took for the issue to be resolved, if any.",
    )
    chat_widget_info: Optional[IssueChatWidgetInfo] = None
    created_at: Optional[str] = Field(
        None, description="The time the issue was created."
    )
    csat_responses: Optional[list[CSATResponse]] = Field(
        None, description="The CSAT responses of the issue, if any."
    )
    custom_fields: Optional[dict[str, CustomFieldValue]] = Field(
        None, description="Custom field values associated with the issue."
    )
    customer_portal_visible: Optional[bool] = Field(
        None, description="Whether the issue is visible in the customer portal."
    )
    external_issues: Optional[list[ExternalIssue]] = Field(
        None, description="The external issues associated with the issue, if any."
    )
    first_response_seconds: Optional[int] = Field(
        None,
        description="The time in seconds it took for the first response to the issue, if any.",
    )
    first_response_time: Optional[str] = Field(
        None, description="The time of the first response to the issue, if any."
    )
    id: Optional[str] = Field(None, description="The ID of the issue.")
    latest_message_time: Optional[str] = Field(
        None, description="The time of the latest message in the issue."
    )
    link: Optional[str] = Field(None, description="The link to the issue in Pylon.")
    number: Optional[int] = Field(None, description="The number of the issue.")
    number_of_touches: Optional[int] = Field(
        None, description="The number of times the issue has been touched."
    )
    requester: Optional[MiniContact] = None
    resolution_seconds: Optional[int] = Field(
        None,
        description="The time in seconds it took for the issue to be resolved, if any.",
    )
    resolution_time: Optional[str] = Field(
        None, description="The time of the resolution of the issue, if any."
    )
    slack: Optional[SlackInfo] = None
    snoozed_until_time: Optional[str] = Field(
        None,
        description="The time the issue was snoozed until in RFC3339 format, if any.",
    )
    source: Optional[Source] = Field(
        None,
        description=(
            "The source of the issue."
            "* slack IssueSourceSlack"
            "* microsoft_teams IssueSourceMicrosoftTeams"
            "* microsoft_teams_chat IssueSourceMicrosoftTeamsChat"
            "* chat_widget IssueSourceChatWidget"
            "* email IssueSourceEmail"
            "* manual IssueSourceManual"
            "* form IssueSourceForm"
            "* discord IssueSourceDiscord"
        ),
    )
    state: Optional[str] = Field(
        None,
        description=(
            "The state of the issue. This could be one of "
            '`["new", "waiting_on_you", "waiting_on_customer", "on_hold", "closed"] or a custom status slug.'
        ),
    )
    tags: Optional[list[str]] = Field(
        None, description="Tags associated with the issue."
    )
    team: Optional[MiniTeam] = None
    title: Optional[str] = Field(None, description="The title of the issue.")
    type: Optional[Type1] = Field(
        None,
        description="The type of the issue.\n\n* Conversation IssueTypeConversation\n\n* Ticket IssueTypeTicket",
    )


class Pagination(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    cursor: str = Field(..., description="The cursor for the next page of results.")
    has_next_page: bool = Field(
        ..., description="Indicates if there is a next page of results."
    )


class MiniAccount(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    id: Optional[str] = Field(None, description="The ID of the account.")


class MiniContact(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    email: Optional[str] = Field(None, description="The email of the contact.")
    id: Optional[str] = Field(None, description="The ID of the contact.")


class CSATResponse(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    comment: Optional[str] = Field(
        None, description="The comment of the CSAT response."
    )
    score: Optional[int] = Field(None, description="The score of the CSAT response.")


class IssueChatWidgetInfo(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    page_url: Optional[str] = Field(
        None,
        description="The URL of the page that the user was on when they started the chat widget issue.",
    )


class MiniUser(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    email: Optional[str] = Field(None, description="The email of the user.")
    id: Optional[str] = Field(None, description="The ID of the user.")


class CustomFieldValue(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    slug: Optional[str] = Field(None, description="The slug of the custom field.")
    value: Optional[str] = Field(
        None,
        description=(
            "The value of the custom field. Only to be used for single-valued custom fields. "
            "If unset, the custom field will be unset. If the custom field is a select field, "
            "the value must be the select option slug, which you can find from the GET /custom-fields endpoint."
        ),
    )
    values: Optional[list[str]] = Field(
        None,
        description=(
            "The values of the custom field. Only to be used for multi-valued custom fields (ex. multiselect). "
            "If unset, the custom field will be unset. If the custom field is a multiselect field, "
            "the values must be the select option slugs which you can find from the GET /custom-fields endpoint."
        ),
    )


class ExternalIssue(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    external_id: Optional[str] = Field(
        None,
        description=(
            "The external ID of the external issue."
            "Jira: ID of the issue (autoincrementing number from 10000)."
            "GitHub: Owner/Repo/IssueID."
            "Linear: ID of the issue (UUID)."
            "Asana: ID of the task (Long number)."
        ),
    )
    link: Optional[str] = Field(None, description="Link to the product issue.")
    source: Optional[str] = Field(None, description="The source of the external issue.")


class SlackInfo(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    channel_id: Optional[str] = Field(
        None, description="The Slack channel ID associated with the issue."
    )
    message_ts: Optional[str] = Field(
        None, description="The root message ID of slack message that started issue."
    )
    workspace_id: Optional[str] = Field(
        None, description="The Slack workspace ID associated with the issue."
    )


class Source(Enum):
    """
    The source of the issue.

    * slack IssueSourceSlack

    * microsoft_teams IssueSourceMicrosoftTeams

    * microsoft_teams_chat IssueSourceMicrosoftTeamsChat

    * chat_widget IssueSourceChatWidget

    * email IssueSourceEmail

    * manual IssueSourceManual

    * form IssueSourceForm

    * discord IssueSourceDiscord
    """

    slack = "slack"
    microsoft_teams = "microsoft_teams"
    microsoft_teams_chat = "microsoft_teams_chat"
    chat_widget = "chat_widget"
    email = "email"
    manual = "manual"
    form = "form"
    discord = "discord"


class MiniTeam(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    id: Optional[str] = Field(None, description="The ID of the team.")


class Type1(Enum):
    """
    The type of the issue.

    * Conversation IssueTypeConversation

    * Ticket IssueTypeTicket
    """

    Conversation = "Conversation"
    Ticket = "Ticket"
