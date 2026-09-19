from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from onyx.db.enums import SSOProviderType
from onyx.db.models import SSOProvider
from onyx.db.sso_provider import mask_secret_config_values, sso_login_callback_uri


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


class SSOLoginDomainStatus(BaseModel):
    domain: str
    verified: bool
    # Whether the provider holding this domain is saved. Verification needs a
    # saved claim, so the record shows first and verifying unlocks on save.
    claimed: bool = False
    # The TXT record to publish to prove control. Unset once verified.
    record_host: str | None = None
    record_value: str | None = None


class SSOLoginDomainsResponse(BaseModel):
    domains: list[SSOLoginDomainStatus]


class SSODomainVerifyRequest(BaseModel):
    domain: str


class SSODomainRecordsRequest(BaseModel):
    domains: list[str]


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
        # Only secrets are masked, so the URI computed below matches what the
        # flow sends.
        config = (
            mask_secret_config_values(
                provider.provider_type, provider.config.get_value(apply_mask=False)
            )
            if provider.config
            else {}
        )
        redirect_uri = sso_login_callback_uri(provider, config, web_domain)

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
