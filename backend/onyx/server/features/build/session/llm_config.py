from collections import Counter
from dataclasses import dataclass

from onyx.llm.model_capabilities import get_llm_max_output_tokens, get_model_map
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


@dataclass(frozen=True)
class GatewaySelection:
    """A gateway model pick: a specific accessible provider row + model name.
    Its ``wire_id`` is the id the gateway routes on."""

    provider_id: int
    model_name: str

    @property
    def wire_id(self) -> str:
        return f"{self.provider_id}/{self.model_name}"

    def to_columns(self) -> tuple[str, str]:
        """The (agent_provider, agent_model) BuildSession columns."""
        return ONYX_GATEWAY_PROVIDER_ID, self.wire_id


@dataclass(frozen=True)
class LegacySelection:
    """A pre-gateway pick, keyed by provider type (no gateway routing)."""

    provider_type: str
    model_name: str


# The persisted agent_provider/agent_model columns decode to one of these; the
# selection is re-validated against currently-accessible providers on every use
# (a stored pick may no longer be accessible or visible), so it is never trusted
# as-is — see _select_gateway_default.
AgentSelection = GatewaySelection | LegacySelection


def parse_agent_selection(
    agent_provider: str | None, agent_model: str | None
) -> AgentSelection | None:
    """Decode the persisted (agent_provider, agent_model) columns. Gateway rows
    store ("onyx", "<provider_id>/<model_name>"); legacy rows store
    (provider_type, model_name). Model names may contain slashes, so the gateway
    id splits on the FIRST separator only."""
    if not agent_model:
        return None
    if agent_provider == ONYX_GATEWAY_PROVIDER_ID:
        provider_id, separator, model_name = agent_model.partition("/")
        if separator and model_name and provider_id.isdigit():
            return GatewaySelection(int(provider_id), model_name)
        return None
    if agent_provider:
        return LegacySelection(agent_provider, agent_model)
    return None


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
    selection: AgentSelection | None,
) -> tuple[int, str] | None:
    if selection is not None:
        for provider in providers:
            matches_request = (
                provider.id == selection.provider_id
                if isinstance(selection, GatewaySelection)
                else provider.provider == selection.provider_type
            )
            if matches_request and any(
                model.is_visible and model.name == selection.model_name
                for model in provider.model_configurations
            ):
                return provider.id, selection.model_name
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
    selection: AgentSelection | None = None,
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
    default_selection = _select_gateway_default(gateway_providers, selection)
    if not visible_models or default_selection is None:
        return None

    clean_display_names = [
        model.custom_display_name or model.display_name or model.name
        for _, model in visible_models
    ]
    display_name_counts = Counter(clean_display_names)
    # Model configs don't track max output tokens; derive it from the litellm
    # map (as the main app does) so opencode's per-model limit is accurate.
    model_map = get_model_map()
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
                max_output_tokens=get_llm_max_output_tokens(
                    model_map, model.name, provider.provider
                ),
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
