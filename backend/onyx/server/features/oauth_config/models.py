from datetime import datetime
from typing import Any

from pydantic import BaseModel


class OAuthConfigCreate(BaseModel):
    name: str
    authorization_url: str
    token_url: str
    client_id: str
    client_secret: str
    scopes: list[str] | None = None
    additional_params: dict[str, Any] | None = None


class OAuthConfigUpdate(BaseModel):
    name: str | None = None
    authorization_url: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: list[str] | None = None
    additional_params: dict[str, Any] | None = None
    clear_client_id: bool = False
    clear_client_secret: bool = False


class OAuthConfigSnapshot(BaseModel):
    id: int
    name: str
    authorization_url: str
    token_url: str
    scopes: list[str] | None
    has_client_credentials: bool  # NEVER expose actual client_id or client_secret
    tool_count: int  # Number of tools using this config
    created_at: datetime
    updated_at: datetime


class OAuthInitiateRequest(BaseModel):
    oauth_config_id: int
    return_path: str = "/chat"  # Where to redirect after OAuth flow


class OAuthInitiateResponse(BaseModel):
    authorization_url: str  # URL to redirect user to
    state: str  # OAuth state parameter for CSRF protection


class OAuthCallbackResponse(BaseModel):
    redirect_url: str
    error: str | None = None


class OAuthTokenStatus(BaseModel):
    oauth_config_id: int
    oauth_config_name: str
    has_token: bool
    expires_at: int | None  # Unix timestamp
    is_expired: bool
