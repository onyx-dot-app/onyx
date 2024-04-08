from danswer.configs.app_configs import DISABLE_GENERATIVE_AI
from danswer.configs.chat_configs import QA_TIMEOUT
from danswer.configs.model_configs import GEN_AI_MODEL_PROVIDER
from danswer.configs.model_configs import GEN_AI_TEMPERATURE
from danswer.llm.chat_llm import DefaultMultiLLM
from danswer.llm.custom_llm import CustomModelServer
from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.gpt_4_all import DanswerGPT4All
from danswer.llm.interfaces import LLM
from danswer.llm.utils import get_default_llm_version
from danswer.llm.utils import get_gen_ai_api_key


def get_default_llm(
    gen_ai_model_provider: str = GEN_AI_MODEL_PROVIDER,
    api_key: str | None = None,
    timeout: int = QA_TIMEOUT,
    temperature: float = GEN_AI_TEMPERATURE,
    use_fast_llm: bool = False,
    gen_ai_model_version_override: str | None = None,
) -> LLM:
    """A single place to fetch the configured LLM for Danswer
    Also allows overriding certain LLM defaults"""
    if DISABLE_GENERATIVE_AI:
        raise GenAIDisabledException()

    if gen_ai_model_version_override:
        model_version = gen_ai_model_version_override
    else:
        base, fast = get_default_llm_version()
        model_version = fast if use_fast_llm else base
    if api_key is None:
        api_key = get_gen_ai_api_key()

    if gen_ai_model_provider.lower() == "custom":
        return CustomModelServer(api_key=api_key, timeout=timeout)

    if gen_ai_model_provider.lower() == "gpt4all":
        return DanswerGPT4All(
            model_version=model_version, timeout=timeout, temperature=temperature
        )

    return DefaultMultiLLM(
        model_version=model_version,
        api_key=api_key,
        timeout=timeout,
        temperature=temperature,
    )
