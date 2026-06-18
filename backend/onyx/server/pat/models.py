"""Pydantic models for Personal Access Token API."""

from datetime import datetime

from pydantic import BaseModel
from pydantic import computed_field
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from onyx.auth.permissions import resolve_effective_permissions
from onyx.db.enums import Permission
from onyx.db.permissions import parse_permission_values

# Assignable token scopes, grouped by `group_label`. `implies` is derived from the
# permission closure and only drives the UI; require_permission re-derives it at
# request time, which is the real grant.


class PatScopeOption(BaseModel):
    scope: Permission
    group_label: str
    label: str
    description: str

    @computed_field
    @property
    def implies(self) -> list[Permission]:
        covered = resolve_effective_permissions({self.scope.value})
        return sorted(Permission(v) for v in covered if v != self.scope.value)


_ASSIGNABLE_SCOPES: list[PatScopeOption] = [
    PatScopeOption(
        scope=Permission.READ_SEARCH,
        group_label="Search",
        label="Read",
        description="Use search and query endpoints.",
    ),
    PatScopeOption(
        scope=Permission.READ_CHAT,
        group_label="Chat",
        label="Read",
        description="View chat sessions and messages.",
    ),
    PatScopeOption(
        scope=Permission.WRITE_CHAT,
        group_label="Chat",
        label="Write",
        description="Create sessions and send messages.",
    ),
]

SELECTABLE_PAT_SCOPES: dict[Permission, PatScopeOption] = {
    option.scope: option for option in _ASSIGNABLE_SCOPES
}


class CreateTokenRequest(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=100, description="Human-readable token name"
    )
    expiration_days: int | None = Field(
        None,
        ge=1,
        description="Days until expiration. Common values: 7, 30, 365, or null (no expiration). Must be >= 1 if provided.",
    )
    scopes: list[Permission] | None = Field(
        None,
        description="API-surface scopes to limit this token to. null = full user access.",
    )


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_display: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    scopes: list[Permission] | None

    @field_validator("scopes", mode="before")
    @classmethod
    def _coerce_scopes(cls, value: list[str] | None) -> list[Permission] | None:
        # Column stores raw strings; drop any no longer-valid permission.
        return parse_permission_values(value) if value is not None else None


class CreatedTokenResponse(TokenResponse):
    token: str  # Only returned on creation - user must copy it now!
