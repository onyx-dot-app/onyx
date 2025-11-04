"""Pydantic models for Personal Access Token API."""

from datetime import datetime

from pydantic import BaseModel
from pydantic import Field


class CreateTokenRequest(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=100, description="Human-readable token name"
    )
    expiration_days: int | None = Field(
        None,
        ge=1,
        description="Days until expiration. Common values: 7, 30, 365, or null (no expiration). Must be >= 1 if provided.",
    )


class TokenResponse(BaseModel):
    id: int
    name: str
    token_display: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class CreatedTokenResponse(TokenResponse):
    token: str  # Only returned on creation - user must copy it now!
