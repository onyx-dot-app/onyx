"""LLM provider-key credential resolver.

Claims requests bound for the canonical Craft LLM provider hosts (OpenAI,
Anthropic, OpenRouter) and injects the sandbox owner's real, access-scoped
provider key read fresh from ``llm_provider``. The pod ships only a placeholder
apiKey, so the live key never lands in the sandbox. Custom ``api_base`` hosts
are out of scope; only the canonical hosts are claimed.
"""

from __future__ import annotations

from mitmproxy import http

from onyx.auth.constants import API_KEY_HEADER_NAME
from onyx.auth.constants import BEARER_PREFIX
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.users import fetch_user_by_id
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.server.features.build.db.build_session import (
    fetch_all_supported_build_llm_providers,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Canonical host -> (provider type, auth header, value prefix). Only the named
# header is set, so the SDK's anthropic-version etc. survive.
_HOST_TO_PROVIDER: dict[str, tuple[str, str, str]] = {
    "api.openai.com": ("openai", API_KEY_HEADER_NAME, BEARER_PREFIX),
    "api.anthropic.com": ("anthropic", "x-api-key", ""),
    "openrouter.ai": ("openrouter", API_KEY_HEADER_NAME, BEARER_PREFIX),
}


class LLMProviderKeyResolver(CredentialResolver):
    """Injects the sandbox owner's LLM provider key on canonical provider hosts."""

    def claims(
        self,
        request: http.Request,
        ctx: InjectionContext,  # noqa: ARG002
    ) -> bool:
        return request.host.lower() in _HOST_TO_PROVIDER

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        provider_type, header, prefix = _HOST_TO_PROVIDER[request.host.lower()]
        user_id = ctx.sandbox.user_id
        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            user = fetch_user_by_id(db, user_id)
            if user is None:
                raise CredentialUnavailableError(
                    f"sandbox user {short_log_id(user_id)} not found"
                )
            providers = fetch_all_supported_build_llm_providers(db, user)

        # First accessible provider of the type, matching how provisioning picks
        # the key (get_all_build_mode_llm_configs dedups by type, first wins).
        provider = next((p for p in providers if p.provider == provider_type), None)
        if provider is None:
            raise CredentialUnavailableError(
                f"no accessible {provider_type} provider for user {short_log_id(user_id)}"
            )
        if not provider.api_key:
            raise CredentialUnavailableError(
                f"{provider_type} provider for user {short_log_id(user_id)} has no api_key"
            )

        logger.debug(
            "llm_provider_key_resolver.resolved provider=%s host=%s",
            provider_type,
            request.host,
        )
        return {header: f"{prefix}{provider.api_key}"}
