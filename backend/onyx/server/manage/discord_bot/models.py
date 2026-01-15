"""Pydantic models for Discord bot API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# === Bot Config ===


class DiscordBotConfigResponse(BaseModel):
    configured: bool
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class DiscordBotConfigCreateRequest(BaseModel):
    bot_token: str


# === Guild Config ===


class DiscordGuildConfigResponse(BaseModel):
    id: UUID
    guild_id: int | None
    guild_name: str | None
    registered_at: datetime | None
    respond_in_all_public_channels: bool
    default_persona_id: int | None
    enabled: bool

    class Config:
        from_attributes = True


class DiscordGuildConfigCreateResponse(BaseModel):
    id: UUID
    registration_key: str  # Shown once!


class DiscordGuildConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    respond_in_all_public_channels: bool | None = None
    default_persona_id: int | None = None


# === Channel Config ===


class DiscordChannelConfigResponse(BaseModel):
    id: UUID
    channel_id: int
    channel_name: str
    require_bot_invocation: bool
    persona_override_id: int | None
    enabled: bool

    class Config:
        from_attributes = True


class DiscordChannelConfigCreateRequest(BaseModel):
    channel_id: int
    channel_name: str
    require_bot_invocation: bool = True
    persona_override_id: int | None = None


class DiscordChannelConfigUpdateRequest(BaseModel):
    channel_name: str | None = None
    require_bot_invocation: bool | None = None
    persona_override_id: int | None = None
    enabled: bool | None = None
