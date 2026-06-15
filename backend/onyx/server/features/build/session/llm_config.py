"""LLM-provider selection for Craft sessions.

Resolves the default model + the full set of configs to pre-register in
opencode.json at provision time. Pre-registering every accessible
provider lets per-prompt model overrides cross providers without a pod
restart.
"""

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.llm_provider_options import (
    fetch_default_model_for_provider,
)
from onyx.server.features.build.configs import BUILD_MODE_ALLOWED_PROVIDER_TYPES
from onyx.server.features.build.configs import BUILD_MODE_NOT_CONFIGURED_API_KEY
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _recommended_model(provider: LLMProviderView) -> str | None:
    """Recommended model for ``provider``: the type's default from the shared
    config, else the first visible model. ``None`` if no visible model."""
    visible_models = [m for m in provider.model_configurations if m.is_visible]
    if not visible_models:
        return None
    return fetch_default_model_for_provider(provider.provider) or visible_models[0].name


def _config_from_provider(
    provider: LLMProviderView, model_name: str
) -> LLMProviderConfig:
    return LLMProviderConfig(
        provider=provider.provider,
        model_name=model_name,
        api_key=provider.api_key,
        api_base=provider.api_base,
    )


def select_default_llm_config(
    providers: list[LLMProviderView],
    requested_provider_type: str | None,
    requested_model_name: str | None,
) -> LLMProviderConfig:
    """Pick the default LLM config over an already-fetched, access-filtered
    provider list.

    Resolution priority:
    1. The user's requested provider/model (from cookie) when the type is
       present in ``providers``. The model name is taken verbatim — the
       provider's API rejects invalid models, so this also allows non-
       ``is_visible`` models.
    2. Otherwise: highest-priority supported provider with its recommended
       model.

    Raises:
        OnyxError: No accessible supported provider is configured.
    """
    if requested_provider_type and requested_model_name:
        for provider in providers:
            if provider.provider == requested_provider_type:
                return _config_from_provider(provider, requested_model_name)
        logger.warning(
            "Requested provider type %s not accessible, falling back",
            requested_provider_type,
        )

    for provider_type in BUILD_MODE_ALLOWED_PROVIDER_TYPES:
        for provider in providers:
            if provider.provider != provider_type:
                continue
            model_name = _recommended_model(provider)
            if model_name is None:
                continue
            return _config_from_provider(provider, model_name)

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "No accessible LLM provider of a supported type "
        f"({', '.join(BUILD_MODE_ALLOWED_PROVIDER_TYPES)}) is configured.",
    )


def get_all_build_mode_llm_configs(
    providers: list[LLMProviderView],
    default: LLMProviderConfig,
) -> list[LLMProviderConfig]:
    """Every supported provider type, ``default`` first — the org's real config
    when present, else a dummy-key placeholder. Registering all types keeps the
    opencode.json set independent of the org's configured providers, so a
    per-prompt cross-provider override never hits "model not found"; an
    unconfigured provider fails closed via the dummy key.
    """
    configs: list[LLMProviderConfig] = [default]
    seen: set[str] = {default.provider}

    for provider in providers:
        if provider.provider in seen:
            continue
        model_name = _recommended_model(provider)
        if model_name is None:
            continue
        seen.add(provider.provider)
        configs.append(_config_from_provider(provider, model_name))

    # Backfill supported types the org hasn't configured with a dummy-key entry.
    for provider_type in BUILD_MODE_ALLOWED_PROVIDER_TYPES:
        if provider_type in seen:
            continue
        model_name = fetch_default_model_for_provider(provider_type)
        if model_name is None:
            continue
        seen.add(provider_type)
        configs.append(
            LLMProviderConfig(
                provider=provider_type,
                model_name=model_name,
                api_key=BUILD_MODE_NOT_CONFIGURED_API_KEY,
                api_base=None,
            )
        )
    return configs
