"""Pydantic models for Discord bot API."""

from datetime import datetime

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
    id: int
    guild_id: int | None
    guild_name: str | None
    registered_at: datetime | None
    default_persona_id: int | None
    enabled: bool

    class Config:
        from_attributes = True


class DiscordGuildConfigCreateResponse(BaseModel):
    id: int
    registration_key: str  # Shown once!


class DiscordGuildConfigUpdateRequest(BaseModel):
    enabled: bool
    default_persona_id: int | None


# === Channel Config ===


class DiscordChannelConfigResponse(BaseModel):
    id: int
    guild_config_id: int
    channel_id: int
    channel_name: str
    channel_type: str
    is_private: bool
    require_bot_invocation: bool
    thread_only_mode: bool
    persona_override_id: int | None
    enabled: bool

    class Config:
        from_attributes = True


class DiscordChannelConfigUpdateRequest(BaseModel):
    require_bot_invocation: bool
    persona_override_id: int | None
    enabled: bool
    thread_only_mode: bool
