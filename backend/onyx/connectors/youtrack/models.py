"""YouTrack REST entities, holding only the fields the connector requests."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class _YouTrackEntity(BaseModel):
    # YouTrack adds `$type` and any field a nested request names, so unknown
    # keys are ignored rather than rejected.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class VisibilityType(str, Enum):
    UNLIMITED = "UnlimitedVisibility"
    LIMITED = "LimitedVisibility"


class YouTrackRef(_YouTrackEntity):
    id: str


# A helpdesk customer account (YouTrack 2026.1 and later).
CUSTOMER_USER_TYPE: str = "REPORTER"
# Undocumented, read by YouTrack's own UI. A project without it is treated as
# a regular one, whose access rules are the stricter of the two.
HELPDESK_PROJECT_TYPE: str = "HELPDESK"


class YouTrackUser(_YouTrackEntity):
    id: str
    login: str | None = None
    full_name: str | None = Field(default=None, alias="fullName")
    email: str | None = None
    banned: bool = False
    guest: bool = False
    user_type: YouTrackRef | None = Field(default=None, alias="userType")

    @property
    def is_customer(self) -> bool:
        return self.user_type is not None and self.user_type.id == CUSTOMER_USER_TYPE


class YouTrackVisibility(_YouTrackEntity):
    type: VisibilityType = Field(alias="$type")
    permitted_groups: list[YouTrackRef] = Field(
        default_factory=list, alias="permittedGroups"
    )
    permitted_users: list[YouTrackRef] = Field(
        default_factory=list, alias="permittedUsers"
    )

    @property
    def is_restricted(self) -> bool:
        return self.type == VisibilityType.LIMITED


class YouTrackProject(_YouTrackEntity):
    id: str
    short_name: str = Field(alias="shortName")
    name: str
    archived: bool = False
    project_type: YouTrackRef | None = Field(default=None, alias="projectType")

    @property
    def is_helpdesk(self) -> bool:
        return (
            self.project_type is not None
            and self.project_type.id == HELPDESK_PROJECT_TYPE
        )


class YouTrackFieldValue(_YouTrackEntity):
    """One value of a custom field. Which attribute is set depends on the field
    type: `name` for enums, states and versions, `fullName` for users,
    `presentation` for periods, `text` for text fields."""

    name: str | None = None
    full_name: str | None = Field(default=None, alias="fullName")
    presentation: str | None = None
    text: str | None = None

    def display(self) -> str | None:
        return self.name or self.full_name or self.presentation or self.text


class YouTrackProjectField(_YouTrackEntity):
    is_public: bool = Field(default=True, alias="isPublic")


class YouTrackCustomField(_YouTrackEntity):
    # Tells a DateIssueCustomField's epoch-ms value apart from a plain integer.
    type: str = Field(alias="$type")
    name: str
    # Simple fields (string, integer, float, date in epoch ms) send a scalar.
    value: YouTrackFieldValue | list[YouTrackFieldValue] | str | int | float | None = (
        None
    )
    project_custom_field: YouTrackProjectField | None = Field(
        default=None, alias="projectCustomField"
    )


class YouTrackComment(_YouTrackEntity):
    id: str
    text: str | None = None
    deleted: bool = False
    visibility: YouTrackVisibility | None = None


class YouTrackIssue(_YouTrackEntity):
    id: str
    id_readable: str = Field(alias="idReadable")
    summary: str | None = None
    description: str | None = None
    created: int
    updated: int
    resolved: int | None = None
    project: YouTrackProject
    reporter: YouTrackUser | None = None
    custom_fields: list[YouTrackCustomField] = Field(
        default_factory=list, alias="customFields"
    )
    comments: list[YouTrackComment] = Field(default_factory=list)
    comments_count: int | None = Field(default=None, alias="commentsCount")


class YouTrackSlimIssue(_YouTrackEntity):
    id: str
    created: int
    project: YouTrackProject


class YouTrackPermission(_YouTrackEntity):
    id: str
    key: str | None = None


class YouTrackRole(_YouTrackEntity):
    id: str
    permissions: list[YouTrackPermission] = Field(default_factory=list)


# Any other role holder is a group: UserGroup, ProjectTeam, AllUsersGroup or
# RegisteredUsersGroup, all listed by /groups/{id}/users.
USER_HOLDER_TYPE: str = "User"


class ScopeType(str, Enum):
    GLOBAL = "GlobalScope"
    ORGANIZATION = "OrganizationScope"
    PROJECT = "ProjectScope"


class YouTrackHolder(_YouTrackEntity):
    type: str = Field(alias="$type")
    id: str


class YouTrackScope(_YouTrackEntity):
    type: str = Field(alias="$type")
    project: YouTrackRef | None = None
    organization: YouTrackRef | None = None


class YouTrackAssignedRole(_YouTrackEntity):
    """One role granted to a user or group, in one scope."""

    role: YouTrackRef
    holder: YouTrackHolder
    scope: YouTrackScope


class YouTrackOrganization(_YouTrackEntity):
    id: str
    projects: list[YouTrackRef] = Field(default_factory=list)


class YouTrackIssueAccess(_YouTrackEntity):
    """What the permission walk reads per issue."""

    id: str
    project: YouTrackProject
    reporter: YouTrackRef | None = None
    visibility: YouTrackVisibility | None = None
