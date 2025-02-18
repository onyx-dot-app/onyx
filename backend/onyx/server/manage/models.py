from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from ee.onyx.server.manage.models import StandardAnswerCategory
from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from onyx.configs.constants import AuthType
from onyx.context.search.models import SavedSearchSettings
from onyx.db.models import AllowedAnswerFilters
from onyx.db.models import ChannelConfig
from onyx.db.models import SlackBot as SlackAppModel
from onyx.db.models import SlackChannelConfig as SlackChannelConfigModel
from onyx.db.models import User
from onyx.onyxbot.slack.config import VALID_SLACK_FILTERS
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


class UserPreferences(BaseModel):
    chosen_assistants: list[int] | None = None
    hidden_assistants: list[int] = []
    visible_assistants: list[int] = []
    default_model: str | None = None
    auto_scroll: bool | None = None
    pinned_assistants: list[int] | None = None
    shortcut_enabled: bool | None = None
    temperature_override_enabled: bool | None = None


class UserInfo(BaseModel):
    id: str
    email: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    role: UserRole
    preferences: UserPreferences
    oidc_expiry: datetime | None = None
    current_token_created_at: datetime | None = None
    current_token_expiry_length: int | None = None
    is_cloud_superuser: bool = False
    organization_name: str | None = None
    is_anonymous_user: bool | None = None

    @classmethod
    def from_model(
        cls,
        user: User,
        current_token_created_at: datetime | None = None,
        expiry_length: int | None = None,
        is_cloud_superuser: bool = False,
        organization_name: str | None = None,
        is_anonymous_user: bool | None = None,
    ) -> "UserInfo":
        return cls(
            id=str(user.id),
            email=user.email,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            is_verified=user.is_verified,
            role=user.role,
            preferences=(
                UserPreferences(
                    shortcut_enabled=user.shortcut_enabled,
                    auto_scroll=user.auto_scroll,
                    chosen_assistants=user.chosen_assistants,
                    default_model=user.default_model,
                    hidden_assistants=user.hidden_assistants,
                    pinned_assistants=user.pinned_assistants,
                    visible_assistants=user.visible_assistants,
                    temperature_override_enabled=user.temperature_override_enabled,
                )
            ),
            organization_name=organization_name,
            # set to None if TRACK_EXTERNAL_IDP_EXPIRY is False so that we avoid cases
            # where they previously had this set + used OIDC, and now they switched to
            # basic auth are now constantly getting redirected back to the login page
            # since their "oidc_expiry is old"
            oidc_expiry=user.oidc_expiry if TRACK_EXTERNAL_IDP_EXPIRY else None,
            current_token_created_at=current_token_created_at,
            current_token_expiry_length=expiry_length,
            is_cloud_superuser=is_cloud_superuser,
            is_anonymous_user=is_anonymous_user,
        )


class UserByEmail(BaseModel):
    user_email: str


class UserRoleUpdateRequest(BaseModel):
    user_email: str
    new_role: UserRole


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


class SlackBotCreationRequest(BaseModel):
    name: str
    enabled: bool

    bot_token: str
    app_token: str


class SlackBotTokens(BaseModel):
    bot_token: str
    app_token: str
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
    standard_answer_categories: list[StandardAnswerCategory]
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
                PersonaSnapshot.from_model(
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

    @classmethod
    def from_model(cls, slack_bot_model: SlackAppModel) -> "SlackBot":
        return cls(
            id=slack_bot_model.id,
            name=slack_bot_model.name,
            enabled=slack_bot_model.enabled,
            bot_token=slack_bot_model.bot_token,
            app_token=slack_bot_model.app_token,
            configs_count=len(slack_bot_model.slack_channel_configs),
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
