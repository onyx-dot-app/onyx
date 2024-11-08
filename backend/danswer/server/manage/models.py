from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from danswer.auth.schemas import UserRole
from danswer.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from danswer.configs.constants import AuthType
from danswer.danswerbot.slack.config import VALID_SLACK_FILTERS
from danswer.db.models import AllowedAnswerFilters
from danswer.db.models import ChannelConfig
from danswer.db.models import SlackBotConfig as SlackBotConfigModel
from danswer.db.models import SlackBotResponseType
from danswer.db.models import User
from danswer.search.models import SavedSearchSettings
from danswer.server.features.persona.models import PersonaSnapshot
from danswer.server.models import FullUserSnapshot
from danswer.server.models import InvitedUserSnapshot
from ee.danswer.server.manage.models import StandardAnswerCategory


if TYPE_CHECKING:
    pass


class VersionResponse(BaseModel):
    backend_version: str


class AuthTypeResponse(BaseModel):
    auth_type: AuthType
    # specifies whether the current auth setup requires
    # users to have verified emails
    requires_verification: bool


class UserPreferences(BaseModel):
    chosen_assistants: list[int] | None = None
    hidden_assistants: list[int] = []
    visible_assistants: list[int] = []
    recent_assistants: list[int] | None = None
    default_model: str | None = None


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

    @classmethod
    def from_model(
        cls,
        user: User,
        current_token_created_at: datetime | None = None,
        expiry_length: int | None = None,
        is_cloud_superuser: bool = False,
        organization_name: str | None = None,
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
                    chosen_assistants=user.chosen_assistants,
                    default_model=user.default_model,
                    hidden_assistants=user.hidden_assistants,
                    visible_assistants=user.visible_assistants,
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


class SlackBotTokens(BaseModel):
    bot_token: str
    app_token: str
    model_config = ConfigDict(frozen=True)


class SlackBotConfigCreationRequest(BaseModel):
    # currently, a persona is created for each slack bot config
    # in the future, `document_sets` will probably be replaced
    # by an optional `PersonaSnapshot` object. Keeping it like this
    # for now for simplicity / speed of development
    document_sets: list[int] | None = None
    persona_id: (
        int | None
    ) = None  # NOTE: only one of `document_sets` / `persona_id` should be set
    channel_names: list[str]
    respond_tag_only: bool = False
    respond_to_bots: bool = False
    enable_auto_filters: bool = False
    # If no team members, assume respond in the channel to everyone
    respond_member_group_list: list[str] = Field(default_factory=list)
    answer_filters: list[AllowedAnswerFilters] = Field(default_factory=list)
    # list of user emails
    follow_up_tags: list[str] | None = None
    response_type: SlackBotResponseType
    # XXX this is going away soon
    standard_answer_categories: list[int] = Field(default_factory=list)

    @field_validator("answer_filters", mode="before")
    @classmethod
    def validate_filters(cls, value: list[str]) -> list[str]:
        if any(test not in VALID_SLACK_FILTERS for test in value):
            raise ValueError(
                f"Slack Answer filters must be one of {VALID_SLACK_FILTERS}"
            )
        return value

    @model_validator(mode="after")
    def validate_document_sets_and_persona_id(self) -> "SlackBotConfigCreationRequest":
        if self.document_sets and self.persona_id:
            raise ValueError("Only one of `document_sets` / `persona_id` should be set")

        return self


class SlackBotConfig(BaseModel):
    id: int
    persona: PersonaSnapshot | None
    channel_config: ChannelConfig
    response_type: SlackBotResponseType
    # XXX this is going away soon
    standard_answer_categories: list[StandardAnswerCategory]
    enable_auto_filters: bool

    @classmethod
    def from_model(
        cls, slack_bot_config_model: SlackBotConfigModel
    ) -> "SlackBotConfig":
        return cls(
            id=slack_bot_config_model.id,
            persona=(
                PersonaSnapshot.from_model(
                    slack_bot_config_model.persona, allow_deleted=True
                )
                if slack_bot_config_model.persona
                else None
            ),
            channel_config=slack_bot_config_model.channel_config,
            response_type=slack_bot_config_model.response_type,
            # XXX this is going away soon
            standard_answer_categories=[
                StandardAnswerCategory.from_model(standard_answer_category_model)
                for standard_answer_category_model in slack_bot_config_model.standard_answer_categories
            ],
            enable_auto_filters=slack_bot_config_model.enable_auto_filters,
        )


class FullModelVersionResponse(BaseModel):
    current_settings: SavedSearchSettings
    secondary_settings: SavedSearchSettings | None


class AllUsersResponse(BaseModel):
    accepted: list[FullUserSnapshot]
    invited: list[InvitedUserSnapshot]
    accepted_pages: int
    invited_pages: int