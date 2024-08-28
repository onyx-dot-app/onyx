from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import root_validator
from pydantic import validator

from danswer.auth.schemas import UserRole
from danswer.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from danswer.configs.constants import AuthType
from danswer.danswerbot.slack.config import VALID_SLACK_FILTERS
from danswer.db.models import AllowedAnswerFilters
from danswer.db.models import ChannelConfig
from danswer.db.models import SlackBotConfig as SlackBotConfigModel
from danswer.db.models import SlackBotResponseType
from danswer.db.models import StandardAnswer as StandardAnswerModel
from danswer.db.models import StandardAnswerCategory as StandardAnswerCategoryModel
from danswer.db.models import User
from danswer.indexing.models import EmbeddingModelDetail
from danswer.server.features.persona.models import PersonaSnapshot
from danswer.server.models import FullUserSnapshot
from danswer.server.models import InvitedUserSnapshot


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
    chosen_assistants: list[int] | None
    default_model: str | None


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

    @classmethod
    def from_model(
        cls,
        user: User,
        current_token_created_at: datetime | None = None,
        expiry_length: int | None = None,
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
                )
            ),
            # set to None if TRACK_EXTERNAL_IDP_EXPIRY is False so that we avoid cases
            # where they previously had this set + used OIDC, and now they switched to
            # basic auth are now constantly getting redirected back to the login page
            # since their "oidc_expiry is old"
            oidc_expiry=user.oidc_expiry if TRACK_EXTERNAL_IDP_EXPIRY else None,
            current_token_created_at=current_token_created_at,
            current_token_expiry_length=expiry_length,
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

    @classmethod
    def from_model(cls, standard_answer_model: StandardAnswerModel) -> "StandardAnswer":
        return cls(
            id=standard_answer_model.id,
            keyword=standard_answer_model.keyword,
            answer=standard_answer_model.answer,
            categories=[
                StandardAnswerCategory.from_model(standard_answer_category_model)
                for standard_answer_category_model in standard_answer_model.categories
            ],
        )


class StandardAnswerCreationRequest(BaseModel):
    keyword: str
    answer: str
    categories: list[int]

    @validator("categories", pre=True)
    def validate_categories(cls, value: list[int]) -> list[int]:
        if len(value) < 1:
            raise ValueError(
                "At least one category must be attached to a standard answer"
            )
        return value


class SlackBotTokens(BaseModel):
    bot_token: str
    app_token: str

    class Config:
        frozen = True


class SlackBotConfigCreationRequest(BaseModel):
    # currently, a persona is created for each slack bot config
    # in the future, `document_sets` will probably be replaced
    # by an optional `PersonaSnapshot` object. Keeping it like this
    # for now for simplicity / speed of development
    document_sets: list[int] | None
    persona_id: (
        int | None
    )  # NOTE: only one of `document_sets` / `persona_id` should be set
    channel_names: list[str]
    respond_tag_only: bool = False
    respond_to_bots: bool = False
    enable_auto_filters: bool = False
    # If no team members, assume respond in the channel to everyone
    respond_member_group_list: list[str] = []
    answer_filters: list[AllowedAnswerFilters] = []
    # list of user emails
    follow_up_tags: list[str] | None = None
    response_type: SlackBotResponseType
    standard_answer_categories: list[int] = []

    @validator("answer_filters", pre=True)
    def validate_filters(cls, value: list[str]) -> list[str]:
        if any(test not in VALID_SLACK_FILTERS for test in value):
            raise ValueError(
                f"Slack Answer filters must be one of {VALID_SLACK_FILTERS}"
            )
        return value

    @root_validator
    def validate_document_sets_and_persona_id(
        cls, values: dict[str, Any]
    ) -> dict[str, Any]:
        if values.get("document_sets") and values.get("persona_id"):
            raise ValueError("Only one of `document_sets` / `persona_id` should be set")

        return values


class SlackBotConfig(BaseModel):
    id: int
    persona: PersonaSnapshot | None
    channel_config: ChannelConfig
    response_type: SlackBotResponseType
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
            standard_answer_categories=[
                StandardAnswerCategory.from_model(standard_answer_category_model)
                for standard_answer_category_model in slack_bot_config_model.standard_answer_categories
            ],
            enable_auto_filters=slack_bot_config_model.enable_auto_filters,
        )


class FullModelVersionResponse(BaseModel):
    current_model: EmbeddingModelDetail
    secondary_model: EmbeddingModelDetail | None


class AllUsersResponse(BaseModel):
    accepted: list[FullUserSnapshot]
    invited: list[InvitedUserSnapshot]
    accepted_pages: int
    invited_pages: int
