from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.multi_llm import LitellmLLM
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.mock_services.mock_llm_server.server import run_in_thread


@pytest.fixture(scope="module")
def mock_llm_server() -> Generator[str, None, None]:
    with run_in_thread() as base_url:
        yield base_url


@pytest.fixture
def script(mock_llm_server: str) -> Generator[MockLLMScript, None, None]:
    handle = MockLLMScript(mock_llm_server, uuid4().hex)
    try:
        yield handle
    finally:
        handle.close()


@pytest.fixture(autouse=True)
def _no_env_injection() -> Generator[None, None, None]:
    # Env injection reads a deployment setting; off means invoke() does not stream.
    with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False):
        yield


def make_llm(api_base: str) -> LitellmLLM:
    return LitellmLLM(
        api_key="sk-mock-llm-server",
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        model_name="mock-model",
        max_input_tokens=200000,
        api_base=api_base,
    )


@pytest.fixture
def llm(script: MockLLMScript) -> LitellmLLM:
    return make_llm(script.api_base)
