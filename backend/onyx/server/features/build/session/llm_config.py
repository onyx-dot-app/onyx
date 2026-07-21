from collections import Counter

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.llm_provider_options import (
    get_provider_display_name,
)
from onyx.server.features.build.configs import (
    ONYX_GATEWAY_PATH_PREFIX,
    ONYX_GATEWAY_PROVIDER_ID,
    SANDBOX_API_SERVER_URL,
    SANDBOX_PROXY_INJECTED_PLACEHOLDER,
)
from onyx.server.features.build.sandbox.models import (
    GatewayModelConfig,
    LLMProviderConfig,
)
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.logger import setup_logger

logger = setup_logger()

CRAFT_RECOMMENDED_MODEL_NAMES = frozenset(
    {
        "gpt-5.6-sol",
        "gpt-5.5",
        "claude-fable-5",
        "claude-opus-4-8",
        "moonshotai/kimi-k3",
        "z-ai/glm-5.2",
    }
)


def _recommended_model(provider: LLMProviderView) -> str | None:
    return next(
        (
            model.name
            for model in provider.model_configurations
            if model.is_visible and model.name in CRAFT_RECOMMENDED_MODEL_NAMES
        ),
        None,
    )


def _first_visible_model(provider: LLMProviderView) -> str | None:
    return next(
        (model.name for model in provider.model_configurations if model.is_visible),
        None,
    )


def normalize_agent_selection(
    provider_id: int | None, model_name: str
) -> tuple[str, str]:
    if provider_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "provider_id is required when selecting a Craft gateway model.",
        )
    return ONYX_GATEWAY_PROVIDER_ID, f"{provider_id}/{model_name}"


def _gateway_provider_order(
    providers: list[LLMProviderView],
) -> list[LLMProviderView]:
    return sorted(
        providers,
        key=lambda provider: (
            (provider.name or get_provider_display_name(provider.provider)).casefold(),
            provider.id,
        ),
    )


def _select_gateway_default(
    providers: list[LLMProviderView],
    requested_provider_id: int | None,
    requested_provider_type: str | None,
    requested_model_name: str | None,
) -> tuple[int, str] | None:
    if requested_model_name:
        requested_provider = (
            next(
                (
                    provider
                    for provider in providers
                    if provider.id == requested_provider_id
                ),
                None,
            )
            if requested_provider_id is not None
            else next(
                (
                    provider
                    for provider in providers
                    if provider.provider == requested_provider_type
                ),
                None,
            )
        )
        if requested_provider and any(
            model.is_visible and model.name == requested_model_name
            for model in requested_provider.model_configurations
        ):
            return requested_provider.id, requested_model_name
        logger.warning(
            "Requested Craft gateway provider/model is not accessible or visible; "
            "falling back"
        )

    for provider in _gateway_provider_order(providers):
        model_name = _recommended_model(provider)
        if model_name is not None:
            return provider.id, model_name
    for provider in _gateway_provider_order(providers):
        model_name = _first_visible_model(provider)
        if model_name is not None:
            return provider.id, model_name
    return None


def build_onyx_gateway_config(
    gateway_providers: list[LLMProviderView],
    requested_provider_id: int | None = None,
    requested_provider_type: str | None = None,
    requested_model_name: str | None = None,
) -> LLMProviderConfig | None:
    if not SANDBOX_API_SERVER_URL:
        return None

    visible_models = [
        (provider, model)
        for provider in gateway_providers
        for model in provider.model_configurations
        if model.is_visible
    ]
    default_selection = _select_gateway_default(
        gateway_providers,
        requested_provider_id,
        requested_provider_type,
        requested_model_name,
    )
    if not visible_models or default_selection is None:
        return None

    clean_display_names = [
        model.custom_display_name or model.display_name or model.name
        for _, model in visible_models
    ]
    display_name_counts = Counter(clean_display_names)
    models: list[GatewayModelConfig] = []
    for provider, model in visible_models:
        display_name = model.custom_display_name or model.display_name or model.name
        if display_name_counts[display_name] > 1:
            provider_label = provider.name or get_provider_display_name(
                provider.provider
            )
            display_name = f"{display_name} ({provider_label})"
        models.append(
            GatewayModelConfig(
                id=f"{provider.id}/{model.name}",
                display_name=display_name,
                supports_reasoning=model.supports_reasoning,
                max_input_tokens=model.max_input_tokens,
            )
        )

    api_root = SANDBOX_API_SERVER_URL.rstrip("/")
    api_base = f"{api_root}{ONYX_GATEWAY_PATH_PREFIX}/v1"
    default_provider_id, default_model_name = default_selection
    return LLMProviderConfig(
        provider=ONYX_GATEWAY_PROVIDER_ID,
        model_name=f"{default_provider_id}/{default_model_name}",
        # The egress proxy overwrites auth headers for the API host with the
        # sandbox PAT; the key here is never used.
        api_key=SANDBOX_PROXY_INJECTED_PLACEHOLDER,
        api_base=api_base,
        npm="@ai-sdk/openai-compatible",
        display_name="Onyx",
        models=models,
    )
