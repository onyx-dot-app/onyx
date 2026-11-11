from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.db.enums import SupportedLanguage


class UserInfo(BaseModel):
    name: str | None = None
    role: str | None = None
    email: str | None = None
    # Directory profile from the IdP login snapshot (country, department, ...)
    # as ordered {label: value} pairs. Fork feature: lets the model give
    # location/role-aware answers (e.g. country-specific HR policies).
    organization_profile: dict[str, str] = Field(default_factory=dict)
    # Same directory profile plus basic identity, keyed by snake_case
    # `{{user.<key>}}` placeholder key (e.g. department/job_title/city/email),
    # for author-controlled placeholder substitution in agent prompts.
    placeholder_values: dict[str, str] = Field(default_factory=dict)
    # UI language. Drives the reply-language hint in the system prompt.
    language: SupportedLanguage | None = None


class UserMemoryContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID | None = None
    user_info: UserInfo
    user_preferences: str | None = None
    memories: tuple[str, ...] = ()

    def without_memories(self) -> "UserMemoryContext":
        """Return a copy with memories cleared but user info/preferences intact."""
        return UserMemoryContext(
            user_id=self.user_id,
            user_info=self.user_info,
            user_preferences=self.user_preferences,
            memories=(),
        )

    def as_formatted_list(self) -> list[str]:
        """Returns combined list of user info, preferences, and memories."""
        result = []
        if self.user_info.name:
            result.append(f"User's name: {self.user_info.name}")
        if self.user_info.role:
            result.append(f"User's role: {self.user_info.role}")
        if self.user_info.email:
            result.append(f"User's email: {self.user_info.email}")
        for label, value in self.user_info.organization_profile.items():
            result.append(f"User's {label.lower()}: {value}")
        if self.user_preferences:
            result.append(f"User preferences: {self.user_preferences}")
        result.extend(self.memories)
        return result
