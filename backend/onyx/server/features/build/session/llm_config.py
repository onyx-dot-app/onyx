from collections import Counter

from onyx.llm.well_known_providers.llm_provider_options import (
    get_provider_display_name,
)
from onyx.server.features.build.configs import (
    ONYX_GATEWAY_PROVIDER_ID,
    ONYX_SERVER_URL,
    SANDBOX_PROXY_INJECTED_PLACEHOLDER,
)
from onyx.server.features.build.sandbox.models import (
    GatewayModelConfig,
    LLMProviderConfig,
)
from onyx.server.gateway.configs import GATEWAY_PATH_PREFIX
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


def _visible_models_by_name(provider: LLMProviderView) -> list[str]:
    """Sorted: the relationship carries no ORDER BY, and callers' choices end
    up in the rendered opencode config, which must be byte-stable."""
    return sorted(
        model.name for model in provider.model_configurations if model.is_visible
    )


def parse_gateway_model_id(model_id: str) -> tuple[int, str] | None:
    """Split the "<provider_id>/<model_name>" composite id the gateway routes
    on. Model names may themselves contain slashes, so split on the FIRST
    separator only."""
    provider_id, separator, model_name = model_id.partition("/")
    if not separator or not model_name or not provider_id.isdigit():
        return None
    return int(provider_id), model_name


def normalize_agent_selection(provider_id: int, model_name: str) -> tuple[str, str]:
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
        for provider in providers:
            matches_request = (
                provider.id == requested_provider_id
                if requested_provider_id is not None
                else provider.provider == requested_provider_type
            )
            if matches_request and any(
                model.is_visible and model.name == requested_model_name
                for model in provider.model_configurations
            ):
                return provider.id, requested_model_name
        logger.warning(
            "Requested Craft gateway provider/model is not accessible or visible; "
            "falling back"
        )

    ordered = _gateway_provider_order(providers)
    for provider in ordered:
        for name in _visible_models_by_name(provider):
            if name in CRAFT_RECOMMENDED_MODEL_NAMES:
                return provider.id, name
    for provider in ordered:
        names = _visible_models_by_name(provider)
        if names:
            return provider.id, names[0]
    return None


def build_onyx_gateway_config(
    gateway_providers: list[LLMProviderView],
    requested_provider_id: int | None = None,
    requested_provider_type: str | None = None,
    requested_model_name: str | None = None,
) -> LLMProviderConfig | None:
    if not ONYX_SERVER_URL:
        return None

    # Sorted so the rendered config is byte-stable across DB reads: the
    # model_configurations relationship has no ORDER BY, and the per-turn
    # reconcile compares the rendered JSON byte-for-byte to decide whether to
    # restart the opencode instance.
    visible_models = [
        (provider, model)
        for provider in _gateway_provider_order(gateway_providers)
        for model in sorted(
            (m for m in provider.model_configurations if m.is_visible),
            key=lambda m: m.name,
        )
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

    api_root = ONYX_SERVER_URL.rstrip("/")
    api_base = f"{api_root}{GATEWAY_PATH_PREFIX}/v1"
    default_provider_id, default_model_name = default_selection
    return LLMProviderConfig(
        provider=ONYX_GATEWAY_PROVIDER_ID,
        model_name=f"{default_provider_id}/{default_model_name}",
        # The egress proxy overwrites auth headers for the API host with the
        # sandbox PAT; the key here is never used.
        api_key=SANDBOX_PROXY_INJECTED_PLACEHOLDER,
        api_base=api_base,
        npm_package="@ai-sdk/openai-compatible",
        display_name="Onyx",
        models=models,
    )
