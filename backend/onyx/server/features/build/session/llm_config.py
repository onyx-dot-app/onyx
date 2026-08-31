from collections.abc import Sequence
from dataclasses import dataclass

from onyx.llm.well_known_providers.llm_provider_options import (
    get_recommendations,
)
from onyx.server.features.build.configs import (
    ONYX_GATEWAY_PROVIDER_ID,
    ONYX_SERVER_URL,
    SANDBOX_PROXY_INJECTED_PLACEHOLDER,
)
from onyx.server.features.build.sandbox.models import (
    CraftLLMProviderConfig,
)
from onyx.server.gateway.configs import GATEWAY_PATH_PREFIX
from onyx.server.gateway.model_catalog import (
    build_gateway_model_catalog,
    ordered_gateway_providers,
)
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


def _matching_visible_model(
    providers: list[LLMProviderView], selection: AgentSelection
) -> tuple[int, str] | None:
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
    return None


def _select_gateway_default(
    providers: list[LLMProviderView],
    selection: AgentSelection | None,
    configured_defaults: Sequence[GatewaySelection] = (),
) -> tuple[int, str] | None:
    if selection is not None:
        resolved = _matching_visible_model(providers, selection)
        if resolved is not None:
            return resolved
        logger.warning(
            "Requested Craft gateway provider/model is not accessible or visible; "
            "falling back"
        )

    # The admin's configured defaults (e.g. craft then chat) outrank the built-in
    # recommendation, in the given priority order. A configured default that is
    # not visible/accessible falls through to the next one rather than skipping
    # straight to the recommendation.
    for configured_default in configured_defaults:
        resolved = _matching_visible_model(providers, configured_default)
        if resolved is not None:
            return resolved

    # Auto-pick a default: prefer each provider's recommended default model
    # (recommended-models.json, kept current by the update-recommended-models
    # workflow) in provider order, else the first provider's first visible model.
    recommendations = get_recommendations()
    ordered = ordered_gateway_providers(providers)
    fallback: tuple[int, str] | None = None
    for provider in ordered:
        visible = _visible_models_by_name(provider)
        if not visible:
            continue
        default_model = recommendations.get_default_model(provider.provider)
        if default_model is not None and default_model.name in visible:
            return provider.id, default_model.name
        if fallback is None:
            fallback = (provider.id, visible[0])
    return fallback


def build_onyx_gateway_config(
    gateway_providers: list[LLMProviderView],
    selection: AgentSelection | None = None,
    configured_defaults: Sequence[GatewaySelection] = (),
) -> CraftLLMProviderConfig | None:
    if not ONYX_SERVER_URL:
        return None

    models = build_gateway_model_catalog(gateway_providers)
    default_selection = _select_gateway_default(
        gateway_providers, selection, configured_defaults
    )
    if not models or default_selection is None:
        return None

    api_root = ONYX_SERVER_URL.rstrip("/")
    api_base = f"{api_root}{GATEWAY_PATH_PREFIX}/v1"
    default_provider_id, default_model_name = default_selection
    return CraftLLMProviderConfig(
        provider=ONYX_GATEWAY_PROVIDER_ID,
        model_name=f"{default_provider_id}/{default_model_name}",
        # The egress proxy overwrites auth headers for the API host with the
        # sandbox PAT; the key here is never used.
        api_key=SANDBOX_PROXY_INJECTED_PLACEHOLDER,
        api_base=api_base,
        display_name="Onyx",
        models=models,
    )
