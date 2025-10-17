import re
from datetime import datetime
from enum import Enum
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from onyx.configs.constants import AuthType
from onyx.context.search.models import SavedSearchSettings
from onyx.db.models import AllowedAnswerFilters
from onyx.db.models import ChannelConfig
from onyx.db.models import SlackBot as SlackAppModel
from onyx.db.models import SlackChannelConfig as SlackChannelConfigModel
from onyx.db.models import StandardAnswer as StandardAnswerModel
from onyx.db.models import StandardAnswerCategory as StandardAnswerCategoryModel
from onyx.db.models import User
from onyx.onyxbot.slack.config import VALID_SLACK_FILTERS
from onyx.server.features.persona.models import FullPersonaSnapshot
from onyx.server.features.persona.models import PersonaSnapshot
from onyx.server.models import FullUserSnapshot
from onyx.server.models import InvitedUserSnapshot


if TYPE_CHECKING:
    pass


class VersionResponse(BaseModel):
    backend_version: str


class AuthTypeResponse(BaseModel):
    auth_type: AuthType
    # specifies whether the current auth setup requires
    # users to have verified emails
    requires_verification: bool
    anonymous_user_enabled: bool | None = None


class UserSpecificAssistantPreference(BaseModel):
    disabled_tool_ids: list[int]


UserSpecificAssistantPreferences = dict[int, UserSpecificAssistantPreference]


class UserPreferences(BaseModel):
    chosen_assistants: list[int] | None = None
    hidden_assistants: list[int] = []
    visible_assistants: list[int] = []
    default_model: str | None = None
    pinned_assistants: list[int] | None = None
    shortcut_enabled: bool | None = None

    # These will default to workspace settings on the frontend if not set
    auto_scroll: bool | None = None
    temperature_override_enabled: bool | None = None

    # controls which tools are enabled for the user for a specific assistant
    assistant_specific_configs: UserSpecificAssistantPreferences | None = None


class UserPersonalization(BaseModel):
    name: str = ""
    role: str = ""
    use_memories: bool = True
    memories: list[str] = Field(default_factory=list)


class TenantSnapshot(BaseModel):
    tenant_id: str
    number_of_users: int


class TenantInfo(BaseModel):
    invitation: TenantSnapshot | None = None
    new_tenant: TenantSnapshot | None = None


class UserInfo(BaseModel):
    id: str
    email: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    role: UserRole
    preferences: UserPreferences
    personalization: UserPersonalization = Field(default_factory=UserPersonalization)
    oidc_expiry: datetime | None = None
    current_token_created_at: datetime | None = None
    current_token_expiry_length: int | None = None
    is_cloud_superuser: bool = False
    team_name: str | None = None
    is_anonymous_user: bool | None = None
    password_configured: bool | None = None
    tenant_info: TenantInfo | None = None

    @classmethod
    def from_model(
        cls,
        user: User,
        current_token_created_at: datetime | None = None,
        expiry_length: int | None = None,
        is_cloud_superuser: bool = False,
        team_name: str | None = None,
        is_anonymous_user: bool | None = None,
        tenant_info: TenantInfo | None = None,
        assistant_specific_configs: UserSpecificAssistantPreferences | None = None,
    ) -> "UserInfo":
        return cls(
            id=str(user.id),
            email=user.email,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            is_verified=user.is_verified,
            role=user.role,
            password_configured=user.password_configured,
            preferences=(
                UserPreferences(
                    shortcut_enabled=user.shortcut_enabled,
                    chosen_assistants=user.chosen_assistants,
                    default_model=user.default_model,
                    hidden_assistants=user.hidden_assistants,
                    pinned_assistants=user.pinned_assistants,
                    visible_assistants=user.visible_assistants,
                    auto_scroll=user.auto_scroll,
                    temperature_override_enabled=user.temperature_override_enabled,
                    assistant_specific_configs=assistant_specific_configs,
                )
            ),
            team_name=team_name,
            # set to None if TRACK_EXTERNAL_IDP_EXPIRY is False so that we avoid cases
            # where they previously had this set + used OIDC, and now they switched to
            # basic auth are now constantly getting redirected back to the login page
            # since their "oidc_expiry is old"
            oidc_expiry=user.oidc_expiry if TRACK_EXTERNAL_IDP_EXPIRY else None,
            current_token_created_at=current_token_created_at,
            current_token_expiry_length=expiry_length,
            is_cloud_superuser=is_cloud_superuser,
            is_anonymous_user=is_anonymous_user,
            tenant_info=tenant_info,
            personalization=UserPersonalization(
                name=user.personal_name or "",
                role=user.personal_role or "",
                use_memories=user.use_memories,
                memories=[memory.memory_text for memory in (user.memories or [])],
            ),
        )


class UserByEmail(BaseModel):
    user_email: str


class UserRoleUpdateRequest(BaseModel):
    user_email: str
    new_role: UserRole
    explicit_override: bool = False


class UserRoleResponse(BaseModel):
    role: str


class BoostDoc(BaseModel):
    document_id: str
    semantic_id: str
    link: str
    boost: int
    hidden: bool


class BoostUpdateRequest(BaseModel):
    document_id: str
    boost: int


class HiddenUpdateRequest(BaseModel):
    document_id: str
    hidden: bool


class AutoScrollRequest(BaseModel):
    auto_scroll: bool | None


class PersonalizationUpdateRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    use_memories: bool | None = None
    memories: list[str] | None = None


class SlackBotCreationRequest(BaseModel):
    name: str
    enabled: bool

    bot_token: str
    app_token: str
    user_token: str | None = None


class SlackBotTokens(BaseModel):
    bot_token: str
    app_token: str
    user_token: str | None = None
    model_config = ConfigDict(frozen=True)


# TODO No longer in use, remove later
class SlackBotResponseType(str, Enum):
    QUOTES = "quotes"
    CITATIONS = "citations"


class SlackChannelConfigCreationRequest(BaseModel):
    slack_bot_id: int
    # currently, a persona is created for each Slack channel config
    # in the future, `document_sets` will probably be replaced
    # by an optional `PersonaSnapshot` object. Keeping it like this
    # for now for simplicity / speed of development
    document_sets: list[int] | None = None

    # NOTE: only one of `document_sets` / `persona_id` should be set
    persona_id: int | None = None

    channel_name: str
    respond_tag_only: bool = False
    respond_to_bots: bool = False
    is_ephemeral: bool = False
    show_continue_in_web_ui: bool = False
    enable_auto_filters: bool = False
    # If no team members, assume respond in the channel to everyone
    respond_member_group_list: list[str] = Field(default_factory=list)
    answer_filters: list[AllowedAnswerFilters] = Field(default_factory=list)
    # list of user emails
    follow_up_tags: list[str] | None = None
    response_type: SlackBotResponseType
    # XXX this is going away soon
    standard_answer_categories: list[int] = Field(default_factory=list)
    disabled: bool = False

    @field_validator("answer_filters", mode="before")
    @classmethod
    def validate_filters(cls, value: list[str]) -> list[str]:
        if any(test not in VALID_SLACK_FILTERS for test in value):
            raise ValueError(
                f"Slack Answer filters must be one of {VALID_SLACK_FILTERS}"
            )
        return value

    @model_validator(mode="after")
    def validate_document_sets_and_persona_id(
        self,
    ) -> "SlackChannelConfigCreationRequest":
        if self.document_sets and self.persona_id:
            raise ValueError("Only one of `document_sets` / `persona_id` should be set")

        return self


class SlackChannelConfig(BaseModel):
    slack_bot_id: int
    id: int
    persona: PersonaSnapshot | None
    channel_config: ChannelConfig
    # XXX this is going away soon
    standard_answer_categories: list["StandardAnswerCategory"]
    enable_auto_filters: bool
    is_default: bool

    @classmethod
    def from_model(
        cls, slack_channel_config_model: SlackChannelConfigModel
    ) -> "SlackChannelConfig":
        return cls(
            id=slack_channel_config_model.id,
            slack_bot_id=slack_channel_config_model.slack_bot_id,
            persona=(
                FullPersonaSnapshot.from_model(
                    slack_channel_config_model.persona, allow_deleted=True
                )
                if slack_channel_config_model.persona
                else None
            ),
            channel_config=slack_channel_config_model.channel_config,
            # XXX this is going away soon
            standard_answer_categories=[
                StandardAnswerCategory.from_model(standard_answer_category_model)
                for standard_answer_category_model in slack_channel_config_model.standard_answer_categories
            ],
            enable_auto_filters=slack_channel_config_model.enable_auto_filters,
            is_default=slack_channel_config_model.is_default,
        )


class SlackBot(BaseModel):
    """
    This model is identical to the SlackAppModel, but it contains
    a `configs_count` field to make it easier to fetch the number
    of SlackChannelConfigs associated with a SlackBot.
    """

    id: int
    name: str
    enabled: bool
    configs_count: int

    bot_token: str
    app_token: str
    user_token: str | None = None

    @classmethod
    def from_model(cls, slack_bot_model: SlackAppModel) -> "SlackBot":
        return cls(
            id=slack_bot_model.id,
            name=slack_bot_model.name,
            enabled=slack_bot_model.enabled,
            configs_count=len(slack_bot_model.slack_channel_configs),
            bot_token=slack_bot_model.bot_token,
            app_token=slack_bot_model.app_token,
            user_token=slack_bot_model.user_token,
        )


class FullModelVersionResponse(BaseModel):
    current_settings: SavedSearchSettings
    secondary_settings: SavedSearchSettings | None


class AllUsersResponse(BaseModel):
    accepted: list[FullUserSnapshot]
    invited: list[InvitedUserSnapshot]
    slack_users: list[FullUserSnapshot]
    accepted_pages: int
    invited_pages: int
    slack_users_pages: int


class SlackChannel(BaseModel):
    id: str
    name: str


"""
Standard Answer Models

ee only, but needs to be here since it's imported by non-ee models.
"""


class StandardAnswerCategoryCreationRequest(BaseModel):
    name: str


class StandardAnswerCategory(BaseModel):
    id: int
    name: str

    @classmethod
    def from_model(
        cls, standard_answer_category: StandardAnswerCategoryModel
    ) -> "StandardAnswerCategory":
        return cls(
            id=standard_answer_category.id,
            name=standard_answer_category.name,
        )


class StandardAnswer(BaseModel):
    id: int
    keyword: str
    answer: str
    categories: list[StandardAnswerCategory]
    match_regex: bool
    match_any_keywords: bool

    @classmethod
    def from_model(cls, standard_answer_model: StandardAnswerModel) -> "StandardAnswer":
        return cls(
            id=standard_answer_model.id,
            keyword=standard_answer_model.keyword,
            answer=standard_answer_model.answer,
            match_regex=standard_answer_model.match_regex,
            match_any_keywords=standard_answer_model.match_any_keywords,
            categories=[
                StandardAnswerCategory.from_model(standard_answer_category_model)
                for standard_answer_category_model in standard_answer_model.categories
            ],
        )


class StandardAnswerCreationRequest(BaseModel):
    keyword: str
    answer: str
    categories: list[int]
    match_regex: bool
    match_any_keywords: bool

    @field_validator("categories", mode="before")
    @classmethod
    def validate_categories(cls, value: list[int]) -> list[int]:
        if len(value) < 1:
            raise ValueError(
                "At least one category must be attached to a standard answer"
            )
        return value

    @model_validator(mode="after")
    def validate_only_match_any_if_not_regex(self) -> Any:
        if self.match_regex and self.match_any_keywords:
            raise ValueError(
                "Can only match any keywords in keyword mode, not regex mode"
            )

        return self

    @model_validator(mode="after")
    def validate_keyword_if_regex(self) -> Any:
        if not self.match_regex:
            # no validation for keywords
            return self

        try:
            re.compile(self.keyword)
            return self
        except re.error as err:
            if isinstance(err.pattern, bytes):
                raise ValueError(
                    f'invalid regex pattern r"{err.pattern.decode()}" in `keyword`: {err.msg}'
                )
            else:
                pattern = f'r"{err.pattern}"' if err.pattern is not None else ""
                raise ValueError(
                    " ".join(
                        ["invalid regex pattern", pattern, f"in `keyword`: {err.msg}"]
                    )
                )


class ContainerVersions(BaseModel):
    onyx: str
    relational_db: str
    index: str
    nginx: str


class AllVersions(BaseModel):
    stable: ContainerVersions
    dev: ContainerVersions
    migration: ContainerVersions
