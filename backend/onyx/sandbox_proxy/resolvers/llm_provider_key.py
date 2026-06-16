"""LLM provider-key credential resolver.

Claims requests bound for Craft LLM provider hosts and injects the sandbox
owner's real, access-scoped provider key read fresh from ``llm_provider``. The
pod ships only a placeholder apiKey, so the live key never lands in the sandbox.
Supports both canonical hosts and dynamic OpenAI-compatible ``api_base`` hosts.
"""

from __future__ import annotations

from urllib.parse import urlparse

from mitmproxy import http

from onyx.auth.constants import API_KEY_HEADER_NAME
from onyx.auth.constants import BEARER_PREFIX
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.users import fetch_user_by_id
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.logging_utils import short_log_id
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.db.build_session import (
    fetch_all_supported_build_llm_providers,
)
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Canonical host -> (provider type, auth header, value prefix). Only the named
# header is set, so the SDK's anthropic-version etc. survive.
_HOST_TO_PROVIDER: dict[str, tuple[str, str, str]] = {
    "api.openai.com": ("openai", API_KEY_HEADER_NAME, BEARER_PREFIX),
    "api.anthropic.com": ("anthropic", "x-api-key", ""),
    "openrouter.ai": ("openrouter", API_KEY_HEADER_NAME, BEARER_PREFIX),
}


def _api_base_host(api_base: str | None) -> str | None:
    if not api_base:
        return None
    parsed = urlparse(api_base)
    return parsed.hostname.lower() if parsed.hostname else None


def _placeholder_auth_present(request: http.Request) -> bool:
    auth = request.headers.get(API_KEY_HEADER_NAME, "")
    if SANDBOX_PROXY_INJECTED_PLACEHOLDER in auth:
        return True
    return request.headers.get("x-api-key", "") == SANDBOX_PROXY_INJECTED_PLACEHOLDER


def _provider_for_request(
    request: http.Request,
    providers: list[LLMProviderView],
) -> tuple[LLMProviderView | None, str, str]:
    host = request.host.lower()
    canonical = _HOST_TO_PROVIDER.get(host)
    if canonical is not None:
        provider_type, header, prefix = canonical
        provider = next((p for p in providers if p.provider == provider_type), None)
        return provider, header, prefix

    provider = next((p for p in providers if _api_base_host(p.api_base) == host), None)
    if provider is None:
        return None, API_KEY_HEADER_NAME, BEARER_PREFIX
    if provider.provider == "anthropic":
        return provider, "x-api-key", ""
    return provider, API_KEY_HEADER_NAME, BEARER_PREFIX


class LLMProviderKeyResolver(CredentialResolver):
    """Injects the sandbox owner's LLM provider key for provider SDK calls."""

    def claims(
        self,
        request: http.Request,
        ctx: InjectionContext,  # noqa: ARG002
    ) -> bool:
        return request.host.lower() in _HOST_TO_PROVIDER or _placeholder_auth_present(
            request
        )

    def resolve(self, request: http.Request, ctx: InjectionContext) -> dict[str, str]:
        user_id = ctx.sandbox.user_id
        with get_session_with_tenant(tenant_id=ctx.sandbox.tenant_id) as db:
            user = fetch_user_by_id(db, user_id)
            if user is None:
                raise CredentialUnavailableError(
                    f"sandbox user {short_log_id(user_id)} not found"
                )
            providers = fetch_all_supported_build_llm_providers(db, user)

        provider, header, prefix = _provider_for_request(request, providers)
        if provider is None:
            raise CredentialUnavailableError(
                f"no accessible LLM provider for host {request.host} "
                f"and user {short_log_id(user_id)}"
            )
        if not provider.api_key:
            raise CredentialUnavailableError(
                f"{provider.provider} provider for user {short_log_id(user_id)} "
                "has no api_key"
            )

        logger.debug(
            "llm_provider_key_resolver.resolved provider=%s host=%s",
            provider.provider,
            request.host,
        )
        return {header: f"{prefix}{provider.api_key}"}
