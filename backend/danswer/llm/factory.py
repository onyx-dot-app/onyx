from danswer.configs.app_configs import DISABLE_GENERATIVE_AI
from danswer.configs.chat_configs import QA_TIMEOUT
from danswer.configs.model_configs import GEN_AI_TEMPERATURE
from danswer.configs.model_configs import LITELLM_EXTRA_HEADERS
from danswer.db.engine import get_session_context_manager
from danswer.db.llm import fetch_default_provider
from danswer.db.llm import fetch_provider
from danswer.db.models import Persona
from danswer.llm.chat_llm import DefaultMultiLLM
from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.interfaces import LLM
from danswer.llm.override_models import LLMOverride


def get_llm_for_persona(
    persona: Persona, llm_override: LLMOverride | None = None
) -> LLM:
    model_provider_override = llm_override.model_provider if llm_override else None
    model_version_override = llm_override.model_version if llm_override else None
    temperature_override = llm_override.temperature if llm_override else None

    return get_default_llm(
        model_provider_name=(
            model_provider_override or persona.llm_model_provider_override
        ),
        model_version=(model_version_override or persona.llm_model_version_override),
        temperature=temperature_override or GEN_AI_TEMPERATURE,
    )


def get_default_llm(
    timeout: int = QA_TIMEOUT,
    temperature: float = GEN_AI_TEMPERATURE,
    use_fast_llm: bool = False,
    model_provider_name: str | None = None,
    model_version: str | None = None,
) -> LLM:
    if DISABLE_GENERATIVE_AI:
        raise GenAIDisabledException()

    # TODO: pass this in
    with get_session_context_manager() as session:
        if model_provider_name is None:
            llm_provider = fetch_default_provider(session)
        else:
            llm_provider = fetch_provider(session, model_provider_name)

    if not llm_provider:
        raise ValueError("No default LLM provider found")

    model_name = model_version or (
        (llm_provider.fast_default_model_name or llm_provider.default_model_name)
        if use_fast_llm
        else llm_provider.default_model_name
    )
    if not model_name:
        raise ValueError("No default model name found")

    return get_llm(
        provider=llm_provider.provider,
        model=model_name,
        api_key=llm_provider.api_key,
        api_base=llm_provider.api_base,
        api_version=llm_provider.api_version,
        custom_config=llm_provider.custom_config,
        timeout=timeout,
        temperature=temperature,
    )


def get_llm(
    provider: str,
    model: str,
    api_key: str | None = None,
    api_base: str | None = None,
    api_version: str | None = None,
    custom_config: dict[str, str] | None = None,
    temperature: float = GEN_AI_TEMPERATURE,
    timeout: int = QA_TIMEOUT,
) -> LLM:
    return DefaultMultiLLM(
        model_provider=provider,
        model_name=model,
        api_key=api_key,
        api_base=api_base,
        api_version=api_version,
        timeout=timeout,
        temperature=temperature,
        custom_config=custom_config,
        extra_headers=LITELLM_EXTRA_HEADERS,
    )
