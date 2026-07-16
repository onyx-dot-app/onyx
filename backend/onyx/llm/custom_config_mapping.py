"""Maps LLM provider custom_config keys to LiteLLM completion kwargs.

Recognized keys become explicit kwargs and never touch os.environ. Unrecognized
keys are env-only: injected into os.environ for the duration of the call on
self-hosted deployments, dropped on multi-tenant cloud (see
LLM_CUSTOM_CONFIG_ENV_INJECTION_ENABLED).
"""

from dataclasses import dataclass
from typing import Any

from onyx.llm.constants import LlmProviderNames
from onyx.llm.well_known_providers.constants import AWS_ACCESS_KEY_ID_KWARG
from onyx.llm.well_known_providers.constants import (
    AWS_ACCESS_KEY_ID_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import (
    AWS_BEARER_TOKEN_BEDROCK_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import AWS_REGION_NAME_KWARG
from onyx.llm.well_known_providers.constants import AWS_REGION_NAME_KWARG_ENV_VAR_FORMAT
from onyx.llm.well_known_providers.constants import AWS_SECRET_ACCESS_KEY_KWARG
from onyx.llm.well_known_providers.constants import (
    AWS_SECRET_ACCESS_KEY_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import AWS_SESSION_TOKEN_KWARG
from onyx.llm.well_known_providers.constants import (
    AWS_SESSION_TOKEN_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import AZURE_AD_TOKEN_KWARG
from onyx.llm.well_known_providers.constants import AZURE_AD_TOKEN_KWARG_ENV_VAR_FORMAT
from onyx.llm.well_known_providers.constants import LM_STUDIO_API_KEY_CONFIG_KEY
from onyx.llm.well_known_providers.constants import OLLAMA_API_KEY_CONFIG_KEY
from onyx.llm.well_known_providers.constants import VERTEX_AUTH_METHOD_KWARG
from onyx.llm.well_known_providers.constants import VERTEX_AUTH_METHOD_WORKLOAD_IDENTITY
from onyx.llm.well_known_providers.constants import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.well_known_providers.constants import (
    VERTEX_CREDENTIALS_FILE_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import VERTEX_LOCATION_KWARG
from onyx.llm.well_known_providers.constants import VERTEX_PROJECT_KWARG

# Shared by BEDROCK and BEDROCK_CONVERSE: both authenticate through LiteLLM's
# BaseAWSLLM, which accepts these params and prefers `api_key` as the Bedrock
# bearer token over the AWS_BEARER_TOKEN_BEDROCK env var.
_BEDROCK_CUSTOM_CONFIG_KWARGS: dict[str, str] = {
    AWS_REGION_NAME_KWARG: AWS_REGION_NAME_KWARG,
    AWS_REGION_NAME_KWARG_ENV_VAR_FORMAT: AWS_REGION_NAME_KWARG,
    AWS_BEARER_TOKEN_BEDROCK_KWARG_ENV_VAR_FORMAT: "api_key",
    AWS_ACCESS_KEY_ID_KWARG: AWS_ACCESS_KEY_ID_KWARG,
    AWS_ACCESS_KEY_ID_KWARG_ENV_VAR_FORMAT: AWS_ACCESS_KEY_ID_KWARG,
    AWS_SECRET_ACCESS_KEY_KWARG: AWS_SECRET_ACCESS_KEY_KWARG,
    AWS_SECRET_ACCESS_KEY_KWARG_ENV_VAR_FORMAT: AWS_SECRET_ACCESS_KEY_KWARG,
    AWS_SESSION_TOKEN_KWARG: AWS_SESSION_TOKEN_KWARG,
    AWS_SESSION_TOKEN_KWARG_ENV_VAR_FORMAT: AWS_SESSION_TOKEN_KWARG,
}

# custom_config key -> litellm.completion kwarg, per provider. Both the kwarg
# spelling and the env-var spelling map to the same kwarg; when a config
# carries both, the later key in the dict wins (historical behavior).
_PROVIDER_CUSTOM_CONFIG_KWARGS: dict[str, dict[str, str]] = {
    LlmProviderNames.BEDROCK: _BEDROCK_CUSTOM_CONFIG_KWARGS,
    LlmProviderNames.BEDROCK_CONVERSE: _BEDROCK_CUSTOM_CONFIG_KWARGS,
    LlmProviderNames.OLLAMA_CHAT: {OLLAMA_API_KEY_CONFIG_KEY: "api_key"},
    LlmProviderNames.LM_STUDIO: {LM_STUDIO_API_KEY_CONFIG_KEY: "api_key"},
    LlmProviderNames.AZURE: {
        AZURE_AD_TOKEN_KWARG: AZURE_AD_TOKEN_KWARG,
        AZURE_AD_TOKEN_KWARG_ENV_VAR_FORMAT: AZURE_AD_TOKEN_KWARG,
    },
}


@dataclass(frozen=True)
class CustomConfigMapping:
    """Result of mapping a custom_config to LiteLLM kwargs.

    `consumed_keys` is a superset of the keys that produced kwargs: a
    recognized key can be superseded by an explicit provider-level setting
    (e.g. a stored api_key), exactly as an env var would have been.
    """

    model_kwargs: dict[str, Any]
    consumed_keys: frozenset[str]


def _normalize_key(key: str) -> str:
    return key.upper().replace("_", "").replace("-", "")


def _map_vertex_config(custom_config: dict[str, str]) -> CustomConfigMapping:
    kwargs: dict[str, Any] = {}
    consumed: set[str] = set()

    workload_identity = (
        custom_config.get(VERTEX_AUTH_METHOD_KWARG)
        == VERTEX_AUTH_METHOD_WORKLOAD_IDENTITY
    )
    for key, value in custom_config.items():
        if key == VERTEX_AUTH_METHOD_KWARG:
            consumed.add(key)
        elif key in (
            VERTEX_CREDENTIALS_FILE_KWARG,
            VERTEX_CREDENTIALS_FILE_KWARG_ENV_VAR_FORMAT,
        ):
            consumed.add(key)
            # In Workload Identity mode, omit vertex_credentials so LiteLLM
            # falls back to google.auth.default() (the GKE metadata server).
            if not workload_identity:
                kwargs[VERTEX_CREDENTIALS_FILE_KWARG] = value
        elif key in (VERTEX_LOCATION_KWARG, VERTEX_PROJECT_KWARG):
            consumed.add(key)
            kwargs[key] = value

    return CustomConfigMapping(model_kwargs=kwargs, consumed_keys=frozenset(consumed))


def map_custom_config_to_model_kwargs(
    model_provider: str,
    custom_config: dict[str, str] | None,
    api_key: str | None,
    api_base: str | None,
) -> CustomConfigMapping:
    """Translate custom_config entries into litellm.completion kwargs.

    Provider-level `api_key` / `api_base` win over the generic
    `<PROVIDER>_API_KEY` / `<PROVIDER>_API_BASE` config keys, mirroring
    LiteLLM's param-over-env precedence. Provider-specific keys (e.g.
    Bedrock's bearer token) keep their historical clobber semantics and
    always produce a kwarg.
    """
    if not custom_config:
        return CustomConfigMapping(model_kwargs={}, consumed_keys=frozenset())

    # Vertex AI authenticates via service-account credentials or workload
    # identity, never a bare API key, so it skips the generic matcher below.
    if model_provider == LlmProviderNames.VERTEX_AI:
        return _map_vertex_config(custom_config)

    kwargs: dict[str, Any] = {}
    consumed: set[str] = set()

    provider_kwargs = _PROVIDER_CUSTOM_CONFIG_KWARGS.get(model_provider, {})
    for key, value in custom_config.items():
        kwarg = provider_kwargs.get(key)
        if kwarg is not None:
            consumed.add(key)
            kwargs[kwarg] = value

    provider_normalized = _normalize_key(model_provider)
    for key, value in custom_config.items():
        if key in consumed:
            continue
        key_normalized = _normalize_key(key)
        if key_normalized == f"{provider_normalized}APIKEY":
            consumed.add(key)
            if not api_key and "api_key" not in kwargs:
                kwargs["api_key"] = value
        elif key_normalized == f"{provider_normalized}APIBASE":
            consumed.add(key)
            if not api_base and "api_base" not in kwargs:
                kwargs["api_base"] = value

    return CustomConfigMapping(model_kwargs=kwargs, consumed_keys=frozenset(consumed))


def get_unsupported_custom_config_keys(
    model_provider: str,
    custom_config: dict[str, str] | None,
) -> set[str]:
    """Return the custom_config keys with no LiteLLM kwarg equivalent."""
    if not custom_config:
        return set()
    mapping = map_custom_config_to_model_kwargs(
        model_provider=model_provider,
        custom_config=custom_config,
        api_key=None,
        api_base=None,
    )
    return set(custom_config) - set(mapping.consumed_keys)
