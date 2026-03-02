"""Pydantic models for Teams bot API."""

from datetime import datetime

from pydantic import BaseModel


# === Bot Config ===


class TeamsBotConfigResponse(BaseModel):
    configured: bool
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class TeamsBotConfigCreateRequest(BaseModel):
    app_id: str
    app_secret: str
    azure_tenant_id: str | None = None


# === Team Config ===


class TeamsTeamConfigResponse(BaseModel):
    id: int
    team_id: str | None
    team_name: str | None
    registered_at: datetime | None
    default_persona_id: int | None
    enabled: bool

    class Config:
        from_attributes = True


class TeamsTeamConfigCreateResponse(BaseModel):
    id: int
    registration_key: str  # Shown once!


class TeamsTeamConfigUpdateRequest(BaseModel):
    enabled: bool
    default_persona_id: int | None


# === Channel Config ===


class TeamsChannelConfigResponse(BaseModel):
    id: int
    team_config_id: int
    channel_id: str
    channel_name: str
    require_bot_mention: bool
    persona_override_id: int | None
    enabled: bool

    class Config:
        from_attributes = True


class TeamsChannelConfigUpdateRequest(BaseModel):
    require_bot_mention: bool
    persona_override_id: int | None
    enabled: bool
