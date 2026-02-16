from collections.abc import Callable
from typing import Any

from onyx.auth.schemas import UserRole
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import can_user_access_llm_provider
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_default_vision_model
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_existing_models
from onyx.db.llm import fetch_llm_provider_view
from onyx.db.llm import fetch_user_group_ids
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLM
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.override_models import LLMOverride
from onyx.llm.utils import get_max_input_tokens_from_llm_provider
from onyx.llm.utils import model_supports_image_input
from onyx.llm.well_known_providers.constants import OLLAMA_API_KEY_CONFIG_KEY
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.headers import build_llm_extra_headers
from onyx.utils.logger import setup_logger

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


def _get_model_configured_max_input_tokens(
    llm_provider: LLMProviderView,
    model_name: str,
) -> int | None:
    for model_configuration in llm_provider.model_configurations:
        if model_configuration.name == model_name:
            return model_configuration.max_input_tokens
    return None


def _build_model_kwargs(
    provider: str,
    configured_max_input_tokens: int | None,
) -> dict[str, Any]:
    model_kwargs: dict[str, Any] = {}
    if (
        provider == LlmProviderNames.OLLAMA_CHAT
        and configured_max_input_tokens
        and configured_max_input_tokens > 0
    ):
        model_kwargs["num_ctx"] = configured_max_input_tokens
    return model_kwargs


def get_llm_for_persona(
    persona: Persona | None,
    user: User,
    llm_override: LLMOverride | None = None,
    additional_headers: dict[str, str] | None = None,
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
        )

    with get_session_with_current_tenant() as db_session:
        provider_model = fetch_existing_llm_provider(provider_name, db_session)
        if not provider_model:
            raise ValueError("No LLM provider found")

        # Fetch user group IDs for access control check
        user_group_ids = fetch_user_group_ids(db_session, user)

        if not can_user_access_llm_provider(
            provider_model, user_group_ids, persona, user.role == UserRole.ADMIN
        ):
            logger.warning(
                "User %s with persona %s cannot access provider %s. Falling back to default provider.",
                user.id,
                persona.id,
                provider_model.name,
            )
            return get_default_llm(
                temperature=temperature_override or GEN_AI_TEMPERATURE,
                additional_headers=additional_headers,
            )

        llm_provider = LLMProviderView.from_model(provider_model)

    model = model_version_override or persona.llm_model_version_override
    if not model:
        raise ValueError("No model name found")

    return llm_from_provider(
        model_name=model,
        llm_provider=llm_provider,
        temperature=temperature_override,
        additional_headers=additional_headers,
    )


def get_default_llm_with_vision(
    timeout: int | None = None,
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
) -> LLM | None:
    """Get an LLM that supports image input, with the following priority:
    1. Use the designated default vision provider if it exists and supports image input
    2. Fall back to the first LLM provider that supports image input

    Returns None if no providers exist or if no provider supports images.
    """

    def create_vision_llm(provider: LLMProviderView, model: str) -> LLM:
        """Helper to create an LLM if the provider supports image input."""
        return llm_from_provider(
            model_name=model,
            llm_provider=provider,
            timeout=timeout,
            temperature=temperature,
            additional_headers=additional_headers,
        )

    provider_map = {}
    with get_session_with_current_tenant() as db_session:
        # Try the default vision provider first
        default_model = fetch_default_vision_model(db_session)
        if default_model:
            if model_supports_image_input(
                default_model.name, default_model.llm_provider.provider
            ):
                return create_vision_llm(
                    LLMProviderView.from_model(default_model.llm_provider),
                    default_model.name,
                )
        # Fall back to searching all providers
        models = fetch_existing_models(
            db_session=db_session,
            flow_types=[LLMModelFlowType.VISION, LLMModelFlowType.CHAT],
        )

        if not models:
            return None

        for model in models:
            if model.llm_provider_id not in provider_map:
                provider_map[model.llm_provider_id] = LLMProviderView.from_model(
                    model.llm_provider
                )

    # Search for viable vision model followed by chat models
    # Sort models from VISION to CHAT priority
    sorted_models = sorted(
        models,
        key=lambda x: (
            LLMModelFlowType.VISION in x.llm_model_flow_types,
            LLMModelFlowType.CHAT in x.llm_model_flow_types,
        ),
        reverse=True,
    )

    for model in sorted_models:
        if model_supports_image_input(model.name, model.llm_provider.provider):
            return create_vision_llm(
                provider_map[model.llm_provider_id],
                model.name,
            )

    return None


def llm_from_provider(
    model_name: str,
    llm_provider: LLMProviderView,
    timeout: int | None = None,
    temperature: float | None = None,
    additional_headers: dict[str, str] | None = None,
) -> LLM:
    configured_max_input_tokens = _get_model_configured_max_input_tokens(
        llm_provider=llm_provider, model_name=model_name
    )
    model_kwargs = _build_model_kwargs(
        provider=llm_provider.provider,
        configured_max_input_tokens=configured_max_input_tokens,
    )
    max_input_tokens = (
        configured_max_input_tokens
        if configured_max_input_tokens
        else get_max_input_tokens_from_llm_provider(
            llm_provider=llm_provider, model_name=model_name
        )
    )
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
        max_input_tokens=max_input_tokens,
        model_kwargs=model_kwargs,
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
) -> LLM:
    with get_session_with_current_tenant() as db_session:
        model = fetch_default_llm_model(db_session)

        if not model:
            raise ValueError("No default LLM model found")

        return llm_from_provider(
            model_name=model.name,
            llm_provider=LLMProviderView.from_model(model.llm_provider),
            timeout=timeout,
            temperature=temperature,
            additional_headers=additional_headers,
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
    model_kwargs: dict[str, Any] | None = None,
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
        model_kwargs=model_kwargs or {},
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
