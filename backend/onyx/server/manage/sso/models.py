from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider


class SSOProviderCreateRequest(BaseModel):
    name: str
    display_name: str
    provider_type: SSOProviderType
    config: dict[str, Any]
    allowed_email_domains: list[str]


class SSOProviderUpdateRequest(BaseModel):
    display_name: str | None = None
    allowed_email_domains: list[str] | None = None
    config: dict[str, Any] | None = None


class SSOProviderEnabledRequest(BaseModel):
    enabled: bool


class SSOProviderResponse(BaseModel):
    id: int
    name: str
    display_name: str
    provider_type: SSOProviderType
    enabled: bool
    allowed_email_domains: list[str]
    config: dict[str, Any]
    redirect_uri: str

    @classmethod
    def from_model(cls, provider: SSOProvider, web_domain: str) -> SSOProviderResponse:
        config = provider.config.get_value(apply_mask=True) if provider.config else {}

        if provider.provider_type in (
            SSOProviderType.GOOGLE_OAUTH,
            SSOProviderType.OIDC,
        ):
            redirect_uri = f"{web_domain}/api/auth/oidc/{provider.name}/callback"
        else:
            redirect_uri = f"{web_domain}/api/auth/saml/{provider.name}/callback"

        return cls(
            id=provider.id,
            name=provider.name,
            display_name=provider.display_name,
            provider_type=provider.provider_type,
            enabled=provider.enabled,
            allowed_email_domains=provider.allowed_email_domains,
            config=config,
            redirect_uri=redirect_uri,
        )
