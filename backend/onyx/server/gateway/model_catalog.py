from collections import Counter
from collections.abc import Sequence

from onyx.llm.model_capabilities import get_llm_max_output_tokens, get_model_map
from onyx.llm.well_known_providers.llm_provider_options import (
    get_provider_display_name,
)
from onyx.server.gateway.models import (
    GatewayModality,
    GatewayModelCapabilities,
    GatewayModelDescriptor,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView


def gateway_provider_label(provider: LLMProviderView) -> str:
    return provider.name or get_provider_display_name(provider.provider)


def ordered_gateway_providers(
    providers: Sequence[LLMProviderView],
) -> list[LLMProviderView]:
    return sorted(
        providers,
        key=lambda provider: (gateway_provider_label(provider).casefold(), provider.id),
    )


def _model_display_name(model: ModelConfigurationView) -> str:
    return model.custom_display_name or model.display_name or model.name


def build_gateway_model_catalog(
    providers: Sequence[LLMProviderView],
) -> list[GatewayModelDescriptor]:
    """Build provider-neutral metadata for every visible accessible model.

    The order is deterministic because consumers reconcile serialized catalogs.
    """
    visible_models = [
        (provider, model)
        for provider in ordered_gateway_providers(providers)
        for model in sorted(
            (model for model in provider.model_configurations if model.is_visible),
            key=lambda model: model.name,
        )
    ]
    display_name_counts = Counter(
        _model_display_name(model) for _, model in visible_models
    )
    model_map = get_model_map()

    catalog: list[GatewayModelDescriptor] = []
    for provider, model in visible_models:
        display_name = _model_display_name(model)
        if display_name_counts[display_name] > 1:
            display_name = f"{display_name} ({gateway_provider_label(provider)})"

        input_modalities: tuple[GatewayModality, ...] = (
            ("text", "image") if model.supports_image_input else ("text",)
        )
        catalog.append(
            GatewayModelDescriptor(
                id=f"{provider.id}/{model.name}",
                display_name=display_name,
                provider=provider.provider,
                capabilities=GatewayModelCapabilities(
                    input_modalities=input_modalities,
                    supports_reasoning=model.supports_reasoning,
                ),
                max_input_tokens=model.max_input_tokens,
                max_output_tokens=get_llm_max_output_tokens(
                    model_map, model.name, provider.provider
                ),
            )
        )
    return catalog
