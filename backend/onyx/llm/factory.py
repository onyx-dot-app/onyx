from collections.abc import Callable

from sqlalchemy.orm import Session

from onyx.chat.models import PersonaOverrideConfig
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import can_user_access_llm_provider
from onyx.db.llm import fetch_default_provider
from onyx.db.llm import fetch_default_vision_provider
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.llm import fetch_llm_provider_view
from onyx.db.llm import fetch_user_group_ids
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.override_models import LLMOverride
from onyx.llm.utils import get_max_input_tokens_from_llm_provider
from onyx.llm.utils import model_supports_image_input
from onyx.llm.well_known_providers.constants import OLLAMA_API_KEY_CONFIG_KEY
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.headers import build_llm_extra_headers
from onyx.utils.logger import setup_logger
from onyx.utils.long_term_log import LongTermLogger

logger = setup_logger()


def _build_provider_extra_headers(
    provider: str, custom_config: dict[str, str] | None
) -> dict[str, str]:
    if provider == LlmProviderNames.OLLAMA_CHAT and custom_config:
        raw_api_key = custom_config.get(OLLAMA_API_KEY_CONFIG_KEY)
        api_key = raw_api_key.strip() if raw_api_key else None
        if not api_key:
            return {}
        if not api_key.lower().startswith("bearer "):
            api_key = f"Bearer {api_key}"
        return {"Authorization": api_key}

    # Passing these will put Onyx on the OpenRouter leaderboard
    elif provider == LlmProviderNames.OPENROUTER:
        return {
            "HTTP-Referer": "https://onyx.app",
            "X-Title": "Onyx",
        }

    return {}


def get_llm_config_for_persona(
    persona: Persona,
    db_session: Session,
    llm_override: LLMOverride | None = None,
) -> LLMConfig:
    """Get LLM config from persona without access checks.

    This function assumes access to the persona has already been verified.
    Use this when you need the LLM config but don't need to create the full LLM object.
    """
    provider_name_override = llm_override.model_provider if llm_override else None
    model_version_override = llm_override.model_version if llm_override else None
    temperature_override = llm_override.temperature if llm_override else None

    provider_name = provider_name_override or persona.llm_model_provider_override
    if not provider_name:
        llm_provider = fetch_default_provider(db_session)
        if not llm_provider:
            raise ValueError("No default LLM provider found")
        model_name: str | None = llm_provider.default_model_name
    else:
        llm_provider = fetch_llm_provider_view(db_session, provider_name)
        if not llm_provider:
            raise ValueError(f"No LLM provider found with name: {provider_name}")
        model_name = model_version_override or persona.llm_model_version_override
        if not model_name:
            model_name = llm_provider.default_model_name

    if not model_name:
        raise ValueError("No model name found")

    max_input_tokens = get_max_input_tokens_from_llm_provider(
        llm_provider=llm_provider, model_name=model_name
    )

    return LLMConfig(
        model_provider=llm_provider.provider,
        model_name=model_name,
        temperature=temperature_override or GEN_AI_TEMPERATURE,
        api_key=llm_provider.api_key,
        api_base=llm_provider.api_base,
        api_version=llm_provider.api_version,
        deployment_name=llm_provider.deployment_name,
        max_input_tokens=max_input_tokens,
    )


def get_llm_for_persona(
    persona: Persona | PersonaOverrideConfig | None,
    user: User | None,
    llm_override: LLMOverride | None = None,
    additional_headers: dict[str, str] | None = None,
    long_term_logger: LongTermLogger | None = None,
) -> LLM:
    if persona is None:
        logger.warning("No persona provided, using default LLM")
        return get_default_llm()

    provider_name_override = llm_override.model_provider if llm_override else None
    model_version_override = llm_override.model_version if llm_override else None
    temperature_override = llm_override.temperature if llm_override else None

    provider_name = provider_name_override or persona.llm_model_provider_override
    if not provider_name:
        return get_default_llm(
            temperature=temperature_override or GEN_AI_TEMPERATURE,
            additional_headers=additional_headers,
            long_term_logger=long_term_logger,
        )

    with get_session_with_current_tenant() as db_session:
        provider_model = fetch_existing_llm_provider(provider_name, db_session)
        if not provider_model:
            raise ValueError("No LLM provider found")

        # Only check access control for database Persona entities, not PersonaOverrideConfig
        # PersonaOverrideConfig is used for temporary overrides and doesn't have access restrictions
        persona_model = persona if isinstance(persona, Persona) else None

        # Fetch user group IDs for access control check
        user_group_ids = fetch_user_group_ids(db_session, user)

        if not can_user_access_llm_provider(
            provider_model,
            user_group_ids,
            persona_model,
        ):
            logger.warning(
                "User %s with persona %s cannot access provider %s. Falling back to default provider.",
                getattr(user, "id", None),
                getattr(persona_model, "id", None),
                provider_model.name,
            )
            return get_default_llm(
                temperature=temperature_override or GEN_AI_TEMPERATURE,
                additional_headers=additional_headers,
                long_term_logger=long_term_logger,
            )

        llm_provider = LLMProviderView.from_model(provider_model)

    model = model_version_override or persona.llm_model_version_override
    if not model:
        raise ValueError("No model name found")

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

        # If no model-configurations are specified, try default model
        if not provider.model_configurations:
            # Try default_model_name
            if provider.default_model_name and model_supports_image_input(
                provider.default_model_name, provider.provider
            ):
                return create_vision_llm(provider_view, provider.default_model_name)

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


def get_default_llm(
    timeout: int | None = None,
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
    long_term_logger: LongTermLogger | None = None,
) -> LLM:
    with get_session_with_current_tenant() as db_session:
        llm_provider = fetch_default_provider(db_session)

    if not llm_provider:
        raise ValueError("No default LLM provider found")

    model_name = llm_provider.default_model_name
    if not model_name:
        raise ValueError("No default model name found")

    return llm_from_provider(
        model_name=model_name,
        llm_provider=llm_provider,
        timeout=timeout,
        temperature=temperature,
        additional_headers=additional_headers,
        long_term_logger=long_term_logger,
    )


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

    return LitellmLLM(
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


def get_llm_tokenizer_encode_func(llm: LLM) -> Callable[[str], list[int]]:
    """Get the tokenizer encode function for an LLM.

    Args:
        llm: The LLM instance to get the tokenizer for

    Returns:
        A callable that encodes a string into a list of token IDs
    """
    llm_provider = llm.config.model_provider
    llm_model_name = llm.config.model_name

    llm_tokenizer = get_tokenizer(
        model_name=llm_model_name,
        provider_type=llm_provider,
    )
    return llm_tokenizer.encode


def get_llm_token_counter(llm: LLM) -> Callable[[str], int]:
    tokenizer_encode_func = get_llm_tokenizer_encode_func(llm)
    return lambda text: len(tokenizer_encode_func(text))
