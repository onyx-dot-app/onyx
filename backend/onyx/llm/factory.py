import os
from typing import Any

from agents import ModelSettings
from agents.models.interface import Model

from onyx.chat.models import PersonaOverrideConfig
from onyx.configs.app_configs import DISABLE_GENERATIVE_AI
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import fetch_default_provider
from onyx.db.llm import fetch_default_vision_provider
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.llm import fetch_llm_provider_view
from onyx.db.models import Persona
from onyx.llm.chat_llm import DefaultMultiLLM
from onyx.llm.chat_llm import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.chat_llm import VERTEX_LOCATION_KWARG
from onyx.llm.exceptions import GenAIDisabledException
from onyx.llm.interfaces import LLM
from onyx.llm.llm_provider_options import OLLAMA_API_KEY_CONFIG_KEY
from onyx.llm.llm_provider_options import OLLAMA_PROVIDER_NAME
from onyx.llm.llm_provider_options import OPENROUTER_PROVIDER_NAME
from onyx.llm.override_models import LLMOverride
from onyx.llm.utils import get_max_input_tokens_from_llm_provider
from onyx.llm.utils import model_supports_image_input
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.headers import build_llm_extra_headers
from onyx.utils.logger import setup_logger
from onyx.utils.long_term_log import LongTermLogger

logger = setup_logger()


def _build_provider_extra_headers(
    provider: str, custom_config: dict[str, str] | None
) -> dict[str, str]:
    # Ollama Cloud: allow passing Bearer token via custom config for cloud instances
    if provider == OLLAMA_PROVIDER_NAME and custom_config:
        raw_api_key = custom_config.get(OLLAMA_API_KEY_CONFIG_KEY)
        api_key = raw_api_key.strip() if raw_api_key else None
        if not api_key:
            return {}
        if not api_key.lower().startswith("bearer "):
            api_key = f"Bearer {api_key}"
        return {"Authorization": api_key}

    # Passing these will put Onyx on the OpenRouter leaderboard
    elif provider == OPENROUTER_PROVIDER_NAME:
        return {
            "HTTP-Referer": "https://onyx.app",
            "X-Title": "Onyx",
        }

    return {}


def get_main_llm_from_tuple(
    llms: tuple[LLM, LLM],
) -> LLM:
    return llms[0]


def get_llms_for_persona(
    persona: Persona | PersonaOverrideConfig | None,
    llm_override: LLMOverride | None = None,
    additional_headers: dict[str, str] | None = None,
    long_term_logger: LongTermLogger | None = None,
) -> tuple[LLM, LLM]:
    if persona is None:
        logger.warning("No persona provided, using default LLMs")
        return get_default_llms()

    provider_name_override = llm_override.model_provider if llm_override else None
    model_version_override = llm_override.model_version if llm_override else None
    temperature_override = llm_override.temperature if llm_override else None

    provider_name = provider_name_override or persona.llm_model_provider_override
    if not provider_name:
        return get_default_llms(
            temperature=temperature_override or GEN_AI_TEMPERATURE,
            additional_headers=additional_headers,
            long_term_logger=long_term_logger,
        )

    with get_session_with_current_tenant() as db_session:
        llm_provider = fetch_llm_provider_view(db_session, provider_name)

    if not llm_provider:
        raise ValueError("No LLM provider found")

    model = model_version_override or persona.llm_model_version_override
    fast_model = llm_provider.fast_default_model_name or llm_provider.default_model_name
    if not model:
        raise ValueError("No model name found")
    if not fast_model:
        raise ValueError("No fast model name found")

    def _create_llm(model: str) -> LLM:
        return get_llm(
            provider=llm_provider.provider,
            model=model,
            deployment_name=llm_provider.deployment_name,
            api_key=llm_provider.api_key,
            api_base=llm_provider.api_base,
            api_version=llm_provider.api_version,
            custom_config=llm_provider.custom_config,
            temperature=temperature_override,
            additional_headers=additional_headers,
            long_term_logger=long_term_logger,
            max_input_tokens=get_max_input_tokens_from_llm_provider(
                llm_provider=llm_provider, model_name=model
            ),
        )

    return _create_llm(model), _create_llm(fast_model)


def get_llm_model_and_settings_for_persona(
    persona: Persona,
    llm_override: LLMOverride | None = None,
    additional_headers: dict[str, str] | None = None,
) -> tuple[Model, ModelSettings]:
    """Get LitellmModel and settings for a persona.

    Returns a tuple of:
    - LitellmModel instance
    - ModelSettings configured with the persona's parameters
    """
    provider_name_override = llm_override.model_provider if llm_override else None
    model_version_override = llm_override.model_version if llm_override else None
    temperature_override = llm_override.temperature if llm_override else None

    provider_name = provider_name_override or persona.llm_model_provider_override
    model_name = None
    if not provider_name:
        with get_session_with_current_tenant() as db_session:
            llm_provider = fetch_default_provider(db_session)

        if not llm_provider:
            raise ValueError("No default LLM provider found")

        model_name = llm_provider.default_model_name
    else:
        with get_session_with_current_tenant() as db_session:
            llm_provider = fetch_llm_provider_view(db_session, provider_name)

    model = model_version_override or persona.llm_model_version_override or model_name
    if not model:
        raise ValueError("No model name found")
    if not llm_provider:
        raise ValueError("No LLM provider found")

    return get_llm_model_and_settings(
        provider=llm_provider.provider,
        model=model,
        deployment_name=llm_provider.deployment_name,
        api_key=llm_provider.api_key,
        api_base=llm_provider.api_base,
        api_version=llm_provider.api_version,
        custom_config=llm_provider.custom_config,
        temperature=temperature_override,
        additional_headers=additional_headers,
    )


def get_default_llm_with_vision(
    timeout: int | None = None,
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
    long_term_logger: LongTermLogger | None = None,
) -> LLM | None:
    """Get an LLM that supports image input, with the following priority:
    1. Use the designated default vision provider if it exists and supports image input
    2. Fall back to the first LLM provider that supports image input

    Returns None if no providers exist or if no provider supports images.
    """
    if DISABLE_GENERATIVE_AI:
        raise GenAIDisabledException()

    def create_vision_llm(provider: LLMProviderView, model: str) -> LLM:
        """Helper to create an LLM if the provider supports image input."""
        return get_llm(
            provider=provider.provider,
            model=model,
            deployment_name=provider.deployment_name,
            api_key=provider.api_key,
            api_base=provider.api_base,
            api_version=provider.api_version,
            custom_config=provider.custom_config,
            timeout=timeout,
            temperature=temperature,
            additional_headers=additional_headers,
            long_term_logger=long_term_logger,
            max_input_tokens=get_max_input_tokens_from_llm_provider(
                llm_provider=provider, model_name=model
            ),
        )

    with get_session_with_current_tenant() as db_session:
        # Try the default vision provider first
        default_provider = fetch_default_vision_provider(db_session)
        if default_provider and default_provider.default_vision_model:
            if model_supports_image_input(
                default_provider.default_vision_model, default_provider.provider
            ):
                return create_vision_llm(
                    default_provider, default_provider.default_vision_model
                )

        # Fall back to searching all providers
        providers = fetch_existing_llm_providers(db_session)

    if not providers:
        return None

    # Check all providers for viable vision models
    for provider in providers:
        provider_view = LLMProviderView.from_model(provider)

        # First priority: Check if provider has a default_vision_model
        if provider.default_vision_model and model_supports_image_input(
            provider.default_vision_model, provider.provider
        ):
            return create_vision_llm(provider_view, provider.default_vision_model)

        # If no model-configurations are specified, try default models in priority order
        if not provider.model_configurations:
            # Try default_model_name
            if provider.default_model_name and model_supports_image_input(
                provider.default_model_name, provider.provider
            ):
                return create_vision_llm(provider_view, provider.default_model_name)

            # Try fast_default_model_name
            if provider.fast_default_model_name and model_supports_image_input(
                provider.fast_default_model_name, provider.provider
            ):
                return create_vision_llm(
                    provider_view, provider.fast_default_model_name
                )

        # Otherwise, if model-configurations are specified, check each model
        else:
            for model_configuration in provider.model_configurations:
                if model_supports_image_input(
                    model_configuration.name, provider.provider
                ):
                    return create_vision_llm(provider_view, model_configuration.name)

    return None


def llm_from_provider(
    model_name: str,
    llm_provider: LLMProviderView,
    timeout: int | None = None,
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
    long_term_logger: LongTermLogger | None = None,
) -> LLM:
    return get_llm(
        provider=llm_provider.provider,
        model=model_name,
        deployment_name=llm_provider.deployment_name,
        api_key=llm_provider.api_key,
        api_base=llm_provider.api_base,
        api_version=llm_provider.api_version,
        custom_config=llm_provider.custom_config,
        timeout=timeout,
        temperature=temperature,
        additional_headers=additional_headers,
        long_term_logger=long_term_logger,
        max_input_tokens=get_max_input_tokens_from_llm_provider(
            llm_provider=llm_provider, model_name=model_name
        ),
    )


def get_llm_for_contextual_rag(model_name: str, model_provider: str) -> LLM:
    with get_session_with_current_tenant() as db_session:
        llm_provider = fetch_llm_provider_view(db_session, model_provider)
    if not llm_provider:
        raise ValueError("No LLM provider with name {} found".format(model_provider))
    return llm_from_provider(
        model_name=model_name,
        llm_provider=llm_provider,
    )


def get_default_llms(
    timeout: int | None = None,
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
    long_term_logger: LongTermLogger | None = None,
) -> tuple[LLM, LLM]:
    if DISABLE_GENERATIVE_AI:
        raise GenAIDisabledException()

    with get_session_with_current_tenant() as db_session:
        llm_provider = fetch_default_provider(db_session)

    if not llm_provider:
        raise ValueError("No default LLM provider found")

    model_name = llm_provider.default_model_name
    fast_model_name = (
        llm_provider.fast_default_model_name or llm_provider.default_model_name
    )
    if not model_name:
        raise ValueError("No default model name found")
    if not fast_model_name:
        raise ValueError("No fast default model name found")

    def _create_llm(model: str) -> LLM:
        return llm_from_provider(
            model_name=model,
            llm_provider=llm_provider,
            timeout=timeout,
            temperature=temperature,
            additional_headers=additional_headers,
            long_term_logger=long_term_logger,
        )

    return _create_llm(model_name), _create_llm(fast_model_name)


def get_llm(
    provider: str,
    model: str,
    max_input_tokens: int,
    deployment_name: str | None,
    api_key: str | None = None,
    api_base: str | None = None,
    api_version: str | None = None,
    custom_config: dict[str, str] | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
    additional_headers: dict[str, str] | None = None,
    long_term_logger: LongTermLogger | None = None,
) -> LLM:
    if temperature is None:
        temperature = GEN_AI_TEMPERATURE

    extra_headers = build_llm_extra_headers(additional_headers)

    # NOTE: this is needed since Ollama API key is optional
    # User may access Ollama cloud via locally hosted instance (logged in)
    # or just via the cloud API (not logged in, using API key)
    provider_extra_headers = _build_provider_extra_headers(provider, custom_config)
    if provider_extra_headers:
        extra_headers.update(provider_extra_headers)

    return DefaultMultiLLM(
        model_provider=provider,
        model_name=model,
        deployment_name=deployment_name,
        api_key=api_key,
        api_base=api_base,
        api_version=api_version,
        timeout=timeout,
        temperature=temperature,
        custom_config=custom_config,
        extra_headers=extra_headers,
        model_kwargs={},
        long_term_logger=long_term_logger,
        max_input_tokens=max_input_tokens,
    )


def get_llm_model_and_settings(
    provider: str,
    model: str,
    deployment_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    api_version: str | None = None,
    custom_config: dict[str, str] | None = None,
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
    model_kwargs: dict[str, Any] | None = None,
) -> tuple[Model, ModelSettings]:
    from onyx.llm.litellm_singleton import LitellmModel

    if temperature is None:
        temperature = GEN_AI_TEMPERATURE

    extra_headers = build_llm_extra_headers(additional_headers)

    # NOTE: this is needed since Ollama API key is optional
    # User may access Ollama cloud via locally hosted instance (logged in)
    # or just via the cloud API (not logged in, using API key)
    provider_extra_headers = _build_provider_extra_headers(provider, custom_config)
    if provider_extra_headers:
        extra_headers.update(provider_extra_headers)

    # NOTE: have to set these as environment variables for Litellm since
    # not all are able to passed in but they always support them set as env
    # variables. We'll also try passing them in, since litellm just ignores
    # addtional kwargs (and some kwargs MUST be passed in rather than set as
    # env variables)
    model_kwargs = model_kwargs or {}
    if custom_config:
        for k, v in custom_config.items():
            os.environ[k] = v
    if custom_config and provider == "vertex_ai":
        for k, v in custom_config.items():
            if k == VERTEX_CREDENTIALS_FILE_KWARG:
                model_kwargs[k] = v
                continue
            elif k == VERTEX_LOCATION_KWARG:
                model_kwargs[k] = v
                continue
    if api_version:
        model_kwargs["api_version"] = api_version
    # Build the full model name in provider/model format
    model_name = f"{provider}/{deployment_name or model}"

    # Create LitellmModel instance
    litellm_model = LitellmModel(
        model=model_name,
        # NOTE: have to pass in None instead of empty string for these
        # otherwise litellm can have some issues with bedrock
        base_url=api_base or None,
        api_key=api_key or None,
    )

    # Create ModelSettings with the provided configuration
    model_settings = ModelSettings(
        temperature=temperature,
        include_usage=True,
        extra_headers=extra_headers if extra_headers else None,
        extra_args=model_kwargs,
    )

    return litellm_model, model_settings
